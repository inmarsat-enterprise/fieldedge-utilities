#!/usr/bin/python
import os
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT_NUMBER = int(os.getenv('HOSTREQUEST_PORT', '8008'))


class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        request_length = int(self.headers.get('Content-Length'))
        command = self.rfile.read(request_length).decode()
        # print(f'Request:\n{command}')
        self.send_response(200)
        args = command if '|' in command else command.split(' ')
        shell = '|' in command
        result = subprocess.run(args,
                                capture_output=True,
                                shell=shell,
                                check=True)
        if result.stdout:
            response_body = result.stdout.decode()
        else:
            response_body = result.stderr.decode()
        # print(f'Response:\n{response_body}')
        self.send_header('Content-Length', len(response_body))
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(response_body.encode())


def main():
    server = HTTPServer(('localhost', PORT_NUMBER), RequestHandler)
    server.serve_forever()


if __name__ == '__main__':
    main()
