MENSAGEM_ENTRADA_PADRAO = "Nova entrada: Veículo *{PLACA}* - cor *{COR}*"


def formatar_template_mensagem(template, placa, cor_veiculo):
    if not template:
        return ""

    mensagem = template
    mensagem = mensagem.replace("{PLACA}", placa or "")
    mensagem = mensagem.replace("{COR}", cor_veiculo or "")
    mensagem = mensagem.replace("{MANUTENCOES}", "")
    return mensagem.strip()
