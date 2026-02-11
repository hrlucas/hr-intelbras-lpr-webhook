import logging
import os
import threading
import time

import requests


class NotificadorWhatsApp:
    def __init__(self, url_api=None, destinatarios=None):
        if url_api is None:
            porta_env = os.getenv("API_WHATSAPP_PORT", "").strip()
            if not porta_env:
                raise ValueError("API_WHATSAPP_PORT não definido no .env")
            try:
                porta_int = int(porta_env)
            except ValueError as exc:
                raise ValueError(f"API_WHATSAPP_PORT inválido: {porta_env}") from exc
            if porta_int < 1 or porta_int > 65535:
                raise ValueError(f"API_WHATSAPP_PORT inválido: {porta_env}")
            url_api = f"http://127.0.0.1:{porta_int}/api/send"

        self.url_api = url_api
        self.destinatarios = destinatarios or ""
        self.url_base = url_api.replace("/api/send", "")
        self.intervalo_alerta = 30
        self.ultimo_alerta = 0

        self.logger = logging.getLogger("WHATSAPP")
        self.logger.setLevel(logging.INFO)
        formatador = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        if not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
            handler_console = logging.StreamHandler()
            handler_console.setFormatter(formatador)
            self.logger.addHandler(handler_console)

        diretorio_base = os.path.dirname(os.path.abspath(__file__))
        diretorio_logs = os.path.join(diretorio_base, "logs")
        os.makedirs(diretorio_logs, exist_ok=True)
        arquivo_erros = os.path.join(diretorio_logs, "erros.log")
        if not any(
            isinstance(h, logging.FileHandler)
            and getattr(h, "baseFilename", "") == os.path.abspath(arquivo_erros)
            for h in self.logger.handlers
        ):
            handler_erro = logging.FileHandler(arquivo_erros, encoding="utf-8")
            handler_erro.setLevel(logging.ERROR)
            handler_erro.setFormatter(formatador)
            self.logger.addHandler(handler_erro)

        self.logger.propagate = False
        self._iniciar_thread_alerta()

    def _iniciar_thread_alerta(self):
        def worker_alerta():
            time.sleep(30)
            while True:
                time.sleep(self.intervalo_alerta)
                if not self._verificar_status():
                    now = time.time()
                    if now - self.ultimo_alerta >= self.intervalo_alerta:
                        self.logger.warning(
                            f"WhatsApp não conectado - para conectar acesse {self.url_base}"
                        )
                        self.ultimo_alerta = now

        thread = threading.Thread(target=worker_alerta, daemon=True)
        thread.start()

    def _obter_lista_destinatarios(self, destinatarios=None):
        raw = destinatarios if destinatarios is not None else self.destinatarios
        if not raw:
            return []
        return [dest.strip() for dest in raw.split(",") if dest.strip()]

    def tem_destinatarios(self, destinatarios=None):
        return bool(self._obter_lista_destinatarios(destinatarios))

    def resumo_destinatarios(self, destinatarios=None):
        lista = self._obter_lista_destinatarios(destinatarios)
        if not lista:
            return "nenhum"
        return f"{len(lista)} destinatário(s)"

    def _verificar_status(self):
        try:
            url_status = f"{self.url_base}/api/status"
            resposta = requests.get(url_status, timeout=5)
            if resposta.status_code == 200:
                resultado = resposta.json()
                return resultado.get("status") == "connected"
            self.logger.warning(f"Status endpoint retornou HTTP {resposta.status_code}")
            return False
        except Exception as erro:
            self.logger.error(f"Falha ao consultar status WhatsApp: {erro}")
            return False

    def _enviar_requisicao(self, mensagem, caminho_imagem=None, destinatarios=None):
        arquivo_obj = None
        try:
            if not mensagem or not isinstance(mensagem, str) or not mensagem.strip():
                self.logger.error("Mensagem vazia ou inválida - envio abortado")
                return False

            destinatarios_preparados = self._obter_lista_destinatarios(destinatarios)
            if not destinatarios_preparados:
                self.logger.error("Destinatários vazios ao tentar enviar notificação")
                return False

            destinatarios_utilizados = destinatarios if destinatarios is not None else self.destinatarios
            dados = {"recipients": destinatarios_utilizados, "message": mensagem}
            arquivos = None

            if caminho_imagem and os.path.exists(caminho_imagem):
                arquivo_obj = open(caminho_imagem, "rb")
                arquivos = {"file": (os.path.basename(caminho_imagem), arquivo_obj, "image/jpeg")}

            resposta = requests.post(self.url_api, data=dados, files=arquivos, timeout=45)

            if resposta.status_code == 200:
                try:
                    resultado = resposta.json()
                except ValueError:
                    resultado = {}
                return resultado.get("status") == "success"

            try:
                dados_erro = resposta.json()
            except ValueError:
                dados_erro = None

            preview_resposta = resposta.text.strip()[:500] if hasattr(resposta, "text") else "Sem corpo"
            self.logger.error(
                f"Falha na API WhatsApp: HTTP {resposta.status_code} | Corpo={preview_resposta}"
            )

            if isinstance(dados_erro, dict):
                mensagem_erro = dados_erro.get("message") or dados_erro.get("erro")
                if mensagem_erro:
                    self.logger.error(f"Detalhes da falha: {mensagem_erro}")
                erros_lista = dados_erro.get("erros")
                if isinstance(erros_lista, list):
                    for erro_item in erros_lista:
                        self.logger.error(f"Destino não encontrado: {erro_item}")

            return False

        except requests.exceptions.Timeout:
            self.logger.warning("Timeout ao enviar mensagem WhatsApp")
            if caminho_imagem:
                self.logger.warning("Tentando novamente sem imagem...")
                return self._enviar_requisicao(mensagem, None, destinatarios)
            return False

        except requests.exceptions.RequestException as erro:
            self.logger.error(f"Erro de requisição WhatsApp: {erro}")
            return False

        finally:
            if arquivo_obj:
                arquivo_obj.close()

    @staticmethod
    def _traduzir_cor_veiculo(cor):
        tradutor_cores = {
            "Beige": "Bege",
            "Black": "Preto",
            "Blue": "Azul",
            "Bronze": "Bronze",
            "Brown": "Marrom",
            "Charcoal": "Grafite",
            "Copper": "Cobre",
            "Cream": "Creme",
            "Gold": "Dourado",
            "Gray": "Cinza",
            "Green": "Verde",
            "Maroon": "Vinho",
            "Multicolor": "Multicolorido",
            "Orange": "Laranja",
            "Pink": "Rosa",
            "Purple": "Roxo",
            "Red": "Vermelho",
            "Silver": "Prata",
            "Tan": "Castanho",
            "Turquoise": "Turquesa",
            "Violet": "Violeta",
            "White": "Branco",
            "Yellow": "Amarelo",
        }

        if not cor or cor in {"N/A", "Unknown"}:
            return None

        return tradutor_cores.get(cor, cor)

    def enviar_mensagem(self, mensagem, destinatarios=None, caminho_imagem=None):
        if not mensagem or not isinstance(mensagem, str) or not mensagem.strip():
            self.logger.error("Mensagem vazia ou inválida - envio abortado")
            return "Mensagem não enviada - mensagem vazia ou inválida."

        if not self.tem_destinatarios(destinatarios):
            self.logger.error("Envio abortado - destinatários não configurados")
            return "Mensagem não enviada - destinatários não configurados."

        if not self._verificar_status():
            self.logger.warning("Envio abortado - WhatsApp não conectado")
            return f"Mensagem não enviada - WhatsApp não conectado. Para conectar acesse {self.url_base}"

        sucesso = self._enviar_requisicao(mensagem, caminho_imagem, destinatarios)
        if sucesso:
            return "Mensagem enviada com sucesso."

        self.logger.error("Falha ao enviar mensagem")
        return "Mensagem não enviada - erro ao enviar."

