"""Coletor SMTP mínimo para o ambiente experimental isolado.

Aceita e descarta qualquer mensagem, sem entregar nada a lugar algum. Serve
para que a ferramenta de simulação considere o envio bem-sucedido — e assim
emita o evento de funil correspondente — sem que nenhum e-mail deixe a máquina.
Não retransmite, não armazena e não encaminha: responde ao diálogo SMTP e
descarta o conteúdo.

Deliberadamente não anuncia STARTTLS na resposta ao EHLO, de modo que o cliente
prossiga em texto claro, adequado ao ambiente local e isolado.

Uso:
    python experiments/smtp_sink.py [--host 127.0.0.1] [--port 2525]
Encerre com Ctrl+C.
"""
from __future__ import annotations

import argparse
import socketserver
import sys


class SMTPSinkHandler(socketserver.StreamRequestHandler):
    def _responder(self, linha: str) -> None:
        self.wfile.write((linha + "\r\n").encode("utf-8"))
        self.wfile.flush()

    def handle(self) -> None:
        self._responder("220 sink.local Servico de coleta pronto")
        recebendo_dados = False
        remetente = destinatarios = ""
        while True:
            linha = self.rfile.readline()
            if not linha:
                break
            texto = linha.decode("utf-8", "replace").rstrip("\r\n")

            if recebendo_dados:
                if texto == ".":
                    recebendo_dados = False
                    self._responder("250 OK: mensagem aceita e descartada")
                continue

            comando = texto[:4].upper()
            if comando == "EHLO":
                # Sem STARTTLS: o cliente segue em texto claro.
                self._responder("250-sink.local")
                self._responder("250 SIZE 10485760")
            elif comando == "HELO":
                self._responder("250 sink.local")
            elif comando == "MAIL":
                remetente = texto
                self._responder("250 OK")
            elif comando == "RCPT":
                destinatarios += texto + "; "
                self._responder("250 OK")
            elif comando == "DATA":
                recebendo_dados = True
                self._responder("354 Envie os dados, encerre com <CRLF>.<CRLF>")
            elif comando == "RSET":
                remetente = destinatarios = ""
                self._responder("250 OK")
            elif comando == "NOOP":
                self._responder("250 OK")
            elif comando == "QUIT":
                self._responder("221 Encerrando")
                break
            else:
                self._responder("250 OK")

        if remetente or destinatarios:
            print(f"mensagem descartada | {remetente} -> {destinatarios}")
            sys.stdout.flush()


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor SMTP que descarta tudo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2525)
    args = parser.parse_args()

    servidor = Servidor((args.host, args.port), SMTPSinkHandler)
    print(f"Coletor SMTP ouvindo em {args.host}:{args.port} (descarta tudo)")
    sys.stdout.flush()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
        servidor.shutdown()


if __name__ == "__main__":
    main()
