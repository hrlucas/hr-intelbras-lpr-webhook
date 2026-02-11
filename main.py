from __future__ import annotations

import base64
import ipaddress
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta

import requests
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from sqlalchemy.orm import Session
from waitress import serve

import database
from database import criar_tabelas, inicializar_banco, obter_registros_filtrados
from lpr_mensagens import MENSAGEM_ENTRADA_PADRAO, formatar_template_mensagem
from models import EntradaLPR
from whatsapp_notifier import NotificadorWhatsApp


class LoggerLPR:
    def __init__(self):
        self.logger = logging.getLogger("HR_INTELBRAS_LPR_WEBHOOK")
        self.logger.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        if not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(formatter)
            self.logger.addHandler(console)

        base_dir = os.path.dirname(os.path.abspath(__file__))
        logs_dir = os.path.join(base_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        error_log = os.path.join(logs_dir, "erros.log")
        if not any(
            isinstance(h, logging.FileHandler)
            and getattr(h, "baseFilename", "") == os.path.abspath(error_log)
            for h in self.logger.handlers
        ):
            file_handler = logging.FileHandler(error_log, encoding="utf-8")
            file_handler.setLevel(logging.ERROR)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.logger.propagate = False

    def info(self, message, component=None):
        if component:
            message = f"[{component}] {message}"
        self.logger.info(self._normalize(message))

    def warning(self, message, component=None):
        if component:
            message = f"[{component}] {message}"
        self.logger.warning(self._normalize(message))

    def error(self, message, component=None, details=False):
        if component:
            message = f"[{component}] {message}"
        self.logger.error(self._normalize(message), exc_info=details)

    def _normalize(self, message):
        if not isinstance(message, str):
            return message
        text = message
        if any(ch in text for ch in ("Ã", "Â", "�")):
            try:
                text = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
            except Exception:
                pass
        return text


log = LoggerLPR()

DIRETORIO_BASE = os.path.dirname(os.path.abspath(__file__))
DIRETORIO_STATIC = os.path.join(DIRETORIO_BASE, "static")
DIRETORIO_CAPTURAS = os.path.join(DIRETORIO_STATIC, "captures")
DIRETORIO_ASSETS = os.path.join(DIRETORIO_BASE, "src", "assets")

ASSETS_PERMITIDOS = {
    "logo_hr_systems.svg",
    "logo_hr_azul.svg",
    "whatsapp_hr_api.svg",
    "logo_hr_branco.svg",
}

os.makedirs(DIRETORIO_CAPTURAS, exist_ok=True)

DESTINO_ENTRADAS = ""
MENSAGEM_ENTRADA = ""
notificador_entradas = None

FRONTEND_ALLOWED_IPS = []

RESPOSTA_CAMERA = {"Response": {"Status": 0, "Message": "Success"}}

app = Flask(__name__, static_folder=DIRETORIO_STATIC)
CORS(app, resources={r"/api/*": {"origins": "*"}, r"/*": {"origins": "*"}})


@app.after_request
def adicionar_headers_cors(response):
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response


def obter_sessao_banco():
    return database.nova_sessao()


def limpar_imagens_antigas(directory, days=15):
    try:
        if not os.path.exists(directory):
            return

        now = time.time()
        limit = now - (days * 86400)
        removed = 0

        for filename in os.listdir(directory):
            full_path = os.path.join(directory, filename)
            if os.path.isfile(full_path) and os.path.getmtime(full_path) < limit:
                os.remove(full_path)
                removed += 1

        if removed > 0:
            log.info(f"Limpeza automática: {removed} imagem(ns) removida(s)")

    except Exception as exc:
        log.error(f"Erro na limpeza de imagens: {exc}", details=True)


def obter_ip_local():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return None


def carregar_configuracoes_whatsapp():
    global DESTINO_ENTRADAS, MENSAGEM_ENTRADA
    DESTINO_ENTRADAS = os.getenv("DESTINO_ENTRADAS", "").strip()
    MENSAGEM_ENTRADA = MENSAGEM_ENTRADA_PADRAO


def ler_porta_env(key, mandatory=False):
    value = os.getenv(key, "").strip()
    if not value:
        if mandatory:
            log.error(f"{key} não definido no .env")
        return None

    try:
        port = int(value)
    except ValueError:
        log.error(f"Porta inválida em {key}='{value}'")
        return None

    if port < 1 or port > 65535:
        log.error(f"Porta inválida em {key}='{value}'")
        return None

    return port


def carregar_configuracoes_frontend():
    global FRONTEND_ALLOWED_IPS

    raw = os.getenv("FRONTEND_ALLOWED_IPS", "").strip()
    if not raw:
        FRONTEND_ALLOWED_IPS = []
        return

    candidates = [item.strip() for item in raw.split(",") if item.strip()]
    valid = []
    for item in candidates:
        try:
            if "/" in item:
                ipaddress.ip_network(item, strict=False)
            else:
                ipaddress.ip_address(item)
            valid.append(item)
        except ValueError:
            log.warning(f"FRONTEND_ALLOWED_IPS inválido ignorado: {item}")

    FRONTEND_ALLOWED_IPS = valid


def obter_ip_cliente(req):
    forwarded = req.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (req.remote_addr or "")
    if ip.startswith("::ffff:"):
        ip = ip.replace("::ffff:", "")
    return ip


def ip_frontend_permitido(ip_cliente):
    if not FRONTEND_ALLOWED_IPS and os.getenv("FRONTEND_ALLOWED_IPS"):
        carregar_configuracoes_frontend()

    if not FRONTEND_ALLOWED_IPS:
        return True

    if not ip_cliente:
        return False

    try:
        ip_obj = ipaddress.ip_address(ip_cliente)
    except ValueError:
        return False

    for item in FRONTEND_ALLOWED_IPS:
        try:
            if "/" in item:
                if ip_obj in ipaddress.ip_network(item, strict=False):
                    return True
            else:
                if ip_obj == ipaddress.ip_address(item):
                    return True
        except ValueError:
            continue

    return False


def salvar_registro_lpr(session: Session, data: dict):
    try:
        if not data or not isinstance(data, dict):
            log.error("Dados inválidos recebidos")
            return

        picture = data.get("Picture", {})
        plate_info = picture.get("Plate", {})
        vehicle_info = picture.get("Vehicle", {})
        snap_info = picture.get("SnapInfo", {})

        plate = plate_info.get("PlateNumber")
        plate_color = plate_info.get("PlateColor", "N/A")
        vehicle_color = vehicle_info.get("VehicleColor", "N/A")

        if not plate or not isinstance(plate, str) or len(plate.strip()) < 3:
            log.warning(f"Placa inválida ou ausente: {plate}")
            return

        plate = plate.strip().upper()

        camera_time = snap_info.get("AccurateTime")
        timestamp = datetime.now()
        if camera_time and isinstance(camera_time, str):
            try:
                timestamp = datetime.strptime(camera_time.split(".")[0], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        duplicate_limit = timestamp - timedelta(seconds=30)
        existing = (
            session.query(EntradaLPR)
            .filter(EntradaLPR.placa == plate, EntradaLPR.timestamp >= duplicate_limit)
            .first()
        )
        if existing:
            return

        record = EntradaLPR(
            placa=plate,
            cor_placa=plate_color,
            cor_veiculo=vehicle_color,
            confianca=plate_info.get("Confidence"),
            timestamp=timestamp,
        )
        session.add(record)
        session.commit()
        session.refresh(record)

        image_absolute = None
        pic_data = picture.get("NormalPic", {}) or picture.get("VehiclePic", {})
        image_content = pic_data.get("Content") if isinstance(pic_data, dict) else None

        if image_content and isinstance(image_content, str):
            try:
                if not image_content.startswith("data:image/"):
                    image_bytes = base64.b64decode(image_content)
                else:
                    encoded = image_content.split(",")[1] if "," in image_content else image_content
                    image_bytes = base64.b64decode(encoded)

                if len(image_bytes) >= 1000:
                    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
                    filename = f"{record.id}-{plate}-{timestamp_str}-{uuid.uuid4().hex[:8]}.jpg"
                    image_relative = os.path.join("captures", filename)
                    image_absolute = os.path.join(DIRETORIO_STATIC, image_relative)

                    with open(image_absolute, "wb") as file:
                        file.write(image_bytes)

                    record.caminho_imagem = image_relative
                    session.commit()
                else:
                    log.warning(f"Imagem muito pequena ({len(image_bytes)} bytes), ignorando")

            except Exception as exc:
                log.error(f"Erro ao processar imagem: {exc}")

        log.info(f"LPR salvo: placa={plate}, cor={vehicle_color}")

        if notificador_entradas:
            try:
                translated_color = NotificadorWhatsApp._traduzir_cor_veiculo(vehicle_color)
                color_label = (translated_color or vehicle_color or "não informada").lower()
                message = formatar_template_mensagem(MENSAGEM_ENTRADA, plate, color_label)
                notificador_entradas.enviar_mensagem(message, caminho_imagem=image_absolute)
            except Exception as exc:
                log.error(f"Erro ao enviar mensagem WhatsApp (entradas): {exc}")

    except Exception as exc:
        log.error(f"Erro ao salvar registro LPR: {exc}", details=True)
        session.rollback()


def _processar_webhook_lpr(data, source="TollgateInfo"):
    if not data:
        log.warning(f"Webhook {source} recebido sem payload JSON válido")
        return jsonify(RESPOSTA_CAMERA), 200

    session = obter_sessao_banco()
    try:
        salvar_registro_lpr(session, data)
    finally:
        session.close()

    return jsonify(RESPOSTA_CAMERA), 200


@app.route("/NotificationInfo/TollgateInfo", methods=["POST"])
def tollgate_info():
    try:
        data = request.get_json(silent=True)
        return _processar_webhook_lpr(data, source="TollgateInfo")
    except Exception as exc:
        log.error(f"Erro no TollgateInfo: {exc}", details=True)
        return jsonify(RESPOSTA_CAMERA), 200


@app.route("/NotificationInfo/KeepAlive", methods=["POST"])
def keep_alive():
    return jsonify(RESPOSTA_CAMERA), 200


@app.route("/NotificationInfo/DeviceInfo", methods=["POST"])
def device_info():
    try:
        data = request.get_json(silent=True) or {}
        device_name = data.get("DeviceName", "N/A")
        device_id = data.get("DeviceID", "N/A")
        log.info(f"DeviceInfo: {device_name} (ID: {device_id})")
    except Exception as exc:
        log.error(f"Erro no DeviceInfo: {exc}", details=True)

    return jsonify({"Result": True, "Message": "Success"}), 200


@app.route("/api/records", methods=["GET"])
def obter_registros():
    try:
        plate = request.args.get("placa") or request.args.get("plate")
        start_date = request.args.get("data_inicio") or request.args.get("start_date")
        end_date = request.args.get("data_fim") or request.args.get("end_date")

        session = obter_sessao_banco()
        try:
            records = obter_registros_filtrados(session, plate, start_date, end_date)
            payload = []
            for record in records:
                payload.append(
                    {
                        "id": record.id,
                        "placa": record.placa,
                        "cor_placa": record.cor_placa,
                        "cor_veiculo": record.cor_veiculo,
                        "confianca": record.confianca,
                        "imagem_url": f"/static/{record.caminho_imagem}" if record.caminho_imagem else None,
                        "timestamp": record.timestamp.isoformat(),
                    }
                )
            return jsonify(payload)
        finally:
            session.close()

    except Exception as exc:
        log.error(f"Erro ao buscar registros: {exc}", details=True)
        return jsonify({"erro": "Erro ao buscar registros", "mensagem": str(exc)}), 500


@app.route("/", methods=["GET"])
def index():
    try:
        client_ip = obter_ip_cliente(request)
        if not ip_frontend_permitido(client_ip):
            log.warning(f"Acesso negado ao frontend para IP {client_ip or 'desconhecido'}")
            return "Acesso negado.", 403

        frontend_path = os.path.join(DIRETORIO_BASE, "frontend.html")
        with open(frontend_path, "r", encoding="utf-8") as file:
            html = file.read()

        return app.response_class(response=html, status=200, mimetype="text/html")

    except FileNotFoundError:
        return "Arquivo frontend.html não encontrado", 404
    except Exception as exc:
        return f"Erro ao carregar frontend: {exc}", 500


@app.route("/assets/<path:nome>", methods=["GET"])
def assets(nome):
    client_ip = obter_ip_cliente(request)
    if not ip_frontend_permitido(client_ip):
        log.warning(f"Acesso negado a assets para IP {client_ip or 'desconhecido'}")
        return "Acesso negado.", 403

    filename = os.path.basename(nome)
    if filename not in ASSETS_PERMITIDOS:
        return "Asset não encontrado", 404

    asset_path = os.path.join(DIRETORIO_ASSETS, filename)
    if not os.path.exists(asset_path):
        return "Asset não encontrado", 404

    return send_file(asset_path)


@app.route("/favicon.ico", methods=["GET"])
def favicon():
    client_ip = obter_ip_cliente(request)
    if not ip_frontend_permitido(client_ip):
        log.warning(f"Acesso negado ao favicon para IP {client_ip or 'desconhecido'}")
        return "Acesso negado.", 403

    icon_path = os.path.join(DIRETORIO_ASSETS, "logo_hr_azul.svg")
    if not os.path.exists(icon_path):
        return "", 204

    return send_file(icon_path, mimetype="image/svg+xml")


@app.errorhandler(404)
def nao_encontrado(_error):
    if request.path.startswith("/api/"):
        return jsonify({"erro": "Rota não encontrada"}), 404
    return "<h1>404 - Página não encontrada</h1>", 404


def iniciar_thread_sincronizacao_banco():
    raw_interval = os.getenv("DB_SYNC_INTERVAL_SECONDS", "30").strip()
    try:
        interval = int(raw_interval)
    except ValueError:
        interval = 30
    interval = max(10, interval)

    def worker():
        while True:
            time.sleep(interval)
            try:
                promoted, migrated = database.tentar_promover_para_postgres_e_migrar()
                if promoted:
                    log.info("Sincronização: banco ativo alterado para PostgreSQL")
                if migrated > 0:
                    log.info(f"Sincronização: {migrated} registro(s) local(is) migrado(s)")
            except Exception as exc:
                log.error(f"Erro no monitor de sincronização do banco: {exc}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return interval


if __name__ == "__main__":
    log.info("=" * 60)
    log.info(" " * 11 + "HR INTELBRAS LPR WEBHOOK")
    log.info("=" * 60)

    log.info("[1/5] Carregando variáveis de ambiente...")
    try:
        from dotenv import load_dotenv

        env_path = os.path.join(DIRETORIO_BASE, ".env")
        load_dotenv(env_path)
        log.info("Variáveis de ambiente carregadas do .env")
    except ImportError:
        log.warning("python-dotenv não instalado, usando variáveis do sistema")

    webhook_port = ler_porta_env("WEBHOOK_PORT", mandatory=True)
    whatsapp_port = ler_porta_env("API_WHATSAPP_PORT", mandatory=False)

    if webhook_port is None:
        log.error("WEBHOOK_PORT é obrigatório para iniciar o servidor.")
        sys.exit(1)

    carregar_configuracoes_whatsapp()
    carregar_configuracoes_frontend()

    log.info(f"WhatsApp destino de entradas={DESTINO_ENTRADAS or 'NÃO DEFINIDO'}")
    if not DESTINO_ENTRADAS:
        log.warning("Notificações de entradas via WhatsApp desabilitadas: DESTINO_ENTRADAS não definido no .env")

    if FRONTEND_ALLOWED_IPS:
        log.info(f"Frontend restrito a {len(FRONTEND_ALLOWED_IPS)} IP(s)/rede(s)")
    else:
        log.warning("Frontend liberado para todos os IPs (FRONTEND_ALLOWED_IPS não definido)")

    log.info("[2/5] Inicializando banco (PostgreSQL com fallback SQLite)...")
    try:
        inicializar_banco()
        criar_tabelas()
    except Exception as exc:
        log.error(f"Falha ao inicializar banco: {exc}", details=True)
        sys.exit(1)

    modo_inicial = database.modo_banco_ativo()
    if modo_inicial == "postgres":
        log.info("Banco ativo: PostgreSQL")
    else:
        log.info(f"Banco ativo: SQLite local ({database.caminho_sqlite_local()})")

    try:
        promoted, migrated = database.tentar_promover_para_postgres_e_migrar()
        if promoted:
            log.info("Banco promovido para PostgreSQL na inicialização")
        if migrated > 0:
            log.info(f"Migração inicial: {migrated} registro(s) local(is) migrado(s)")
    except Exception as exc:
        log.warning(f"Não foi possível promover/migrar banco na inicialização: {exc}")

    log.info("[3/5] Iniciando API do WhatsApp...")

    whatsapp_dir = os.path.join(DIRETORIO_BASE, "whatsapp_api")
    whatsapp_process = None
    notificador_entradas = None

    if whatsapp_port is None:
        log.warning("API_WHATSAPP_PORT não definido. WhatsApp desabilitado.")
    else:
        try:
            result = subprocess.run(["node", "--version"], capture_output=True, check=True, text=True)
            log.info(f"Node.js detectado: {result.stdout.strip()}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            log.warning("Node.js não encontrado - WhatsApp desabilitado")
        else:
            try:
                package_json = os.path.join(whatsapp_dir, "package.json")
                if not os.path.exists(package_json):
                    log.warning("whatsapp_api/package.json não encontrado")
                    log.warning("Execute: cd whatsapp_api && npm install")
                else:
                    logs_dir = os.path.join(DIRETORIO_BASE, "logs")
                    os.makedirs(logs_dir, exist_ok=True)
                    whatsapp_log = os.path.join(logs_dir, "erros.log")
                    log_file = open(whatsapp_log, "a", encoding="utf-8")

                    whatsapp_process = subprocess.Popen(
                        ["node", "index.js"],
                        stdout=subprocess.DEVNULL,
                        stderr=log_file,
                        cwd=whatsapp_dir,
                        shell=False,
                        start_new_session=True if os.name != "nt" else False,
                    )

                    log.info("Aguardando inicialização do WhatsApp...")
                    time.sleep(3)

                    if whatsapp_process.poll() is not None:
                        log.error("WhatsApp API falhou ao iniciar")
                        log.error(f"Verifique o log: {whatsapp_log}")
                    else:
                        local_ip = obter_ip_local()
                        whatsapp_url = (
                            f"http://{local_ip}:{whatsapp_port}"
                            if local_ip
                            else f"http://127.0.0.1:{whatsapp_port}"
                        )

                        try:
                            requests.get(whatsapp_url, timeout=2)
                            log.info(f"WhatsApp API rodando em {whatsapp_url}")
                        except requests.exceptions.RequestException:
                            log.warning("WhatsApp API ainda não responde; continuando inicialização")

                        if DESTINO_ENTRADAS:
                            endpoint = f"{whatsapp_url}/api/send"
                            notificador_entradas = NotificadorWhatsApp(endpoint, DESTINO_ENTRADAS)

            except Exception as exc:
                log.error(f"Erro ao iniciar WhatsApp API: {exc}", details=True)

    log.info("[4/5] Ativando monitor de sincronização de banco...")
    interval = iniciar_thread_sincronizacao_banco()
    log.info(f"Monitor de sincronização ativo (intervalo: {interval}s)")

    log.info("[5/5] Iniciando servidor Flask...")
    log.info("=" * 60)
    log.info(" " * 9 + "SERVIDOR INICIADO COM SUCESSO")
    log.info("=" * 60)

    local_ip = obter_ip_local()
    if local_ip:
        log.info(f"Frontend: http://{local_ip}:{webhook_port}/")
        log.info(f"API: http://{local_ip}:{webhook_port}/api/records")
        log.info(f"Webhook: http://{local_ip}:{webhook_port}/NotificationInfo/TollgateInfo")
        if notificador_entradas and whatsapp_port:
            log.info(f"WhatsApp: http://{local_ip}:{whatsapp_port}")
    else:
        log.info(f"Frontend: http://localhost:{webhook_port}/")
        log.info(f"API: http://localhost:{webhook_port}/api/records")
        log.info(f"Webhook: http://localhost:{webhook_port}/NotificationInfo/TollgateInfo")
        if notificador_entradas and whatsapp_port:
            log.info(f"WhatsApp: http://localhost:{whatsapp_port}")

    cpu_count = os.cpu_count() or 4
    waitress_threads = max(8, cpu_count * 4)

    try:
        serve(
            app,
            host="0.0.0.0",
            port=webhook_port,
            threads=waitress_threads,
            connection_limit=1000,
            cleanup_interval=10,
            channel_timeout=120,
        )
    except KeyboardInterrupt:
        log.info("Encerrando servidor...")
        if whatsapp_process:
            log.info("Encerrando WhatsApp API...")
            whatsapp_process.terminate()
            try:
                whatsapp_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                whatsapp_process.kill()
        sys.exit(0)
    except Exception as exc:
        log.error(f"Erro fatal no servidor: {exc}", details=True)
        if whatsapp_process:
            whatsapp_process.terminate()
        sys.exit(1)
