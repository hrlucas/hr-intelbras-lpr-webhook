import os
from datetime import datetime

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass


def _get_webhook_port():
    value = os.getenv("WEBHOOK_PORT", "").strip()
    if not value:
        raise ValueError("WEBHOOK_PORT não definido no .env")

    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"WEBHOOK_PORT inválido: {value}") from exc

    if port < 1 or port > 65535:
        raise ValueError(f"WEBHOOK_PORT inválido: {value}")

    return port


def _get_webhook_host():
    host = os.getenv("WEBHOOK_HOST", "127.0.0.1").strip()
    return host or "127.0.0.1"


def send_fake_plate(plate_number, vehicle_color="Black", plate_color="White"):
    try:
        port = _get_webhook_port()
    except ValueError as error:
        print(f"Erro de configuração: {error}")
        return False

    host = _get_webhook_host()
    url = f"http://{host}:{port}/NotificationInfo/TollgateInfo"

    payload = {
        "Picture": {
            "Plate": {
                "PlateNumber": plate_number.upper(),
                "PlateColor": plate_color,
                "Confidence": 95,
                "IsExist": True,
            },
            "Vehicle": {
                "VehicleColor": vehicle_color,
                "VehicleSeries": "Fake",
                "VehicleSign": "FakeBrand",
                "VehicleType": "Car",
            },
            "SnapInfo": {
                "AccurateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "DeviceID": "FakeDevice",
                "Direction": "Obverse",
                "SnapTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "TriggerSource": "Video",
            },
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"Placa {plate_number} enviada com sucesso.")
        print(f"Status: {response.status_code}")
        print(f"Resposta: {response.json()}")
        return True
    except Exception as error:
        print(f"Erro ao enviar placa {plate_number}: {error}")
        return False


if __name__ == "__main__":
    test_plates = [
        "HRA1234",
        "HRB2345",
        "HRC3456",
        "HRD4567",
        "HRE5678",
        "HRF6789",
        "HRG7890",
        "HRH8901",
        "HRI9012",
        "HRJ0123",
    ]

    print("Enviando placas de teste...")
    for plate in test_plates:
        send_fake_plate(plate)
        print("-" * 40)

    custom_plate = input("Digite uma placa personalizada (ou Enter para sair): ").strip()
    if custom_plate:
        send_fake_plate(custom_plate)
