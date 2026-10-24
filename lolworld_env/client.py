"""LOL-world local League client connection and JSON transport."""
import base64
import json
import re
import ssl
import subprocess
import urllib.error
import urllib.request



class ApiError(RuntimeError):
    def __init__(self, status, method, path, body):
        self.status = status
        super().__init__(f"{method} {path}: HTTP {status}: {body}")


class LoLWorldClient:
    """LOL-world connection to LCU and the local Live Client Data API.

    Discovers a running League client; never launches a game on construction.
    """

    def __init__(self):
        # Capture credentials internally; never print the process command line.
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name = 'LeagueClientUx.exe'\" | "
             "Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, check=True,
        )
        commands = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(commands, str):
            commands = [commands]
        credentials = []
        for command in commands:
            port = re.search(r'--app-port=(\d+)', command or '')
            token = re.search(r'--remoting-auth-token=([^\s"]+)', command or '')
            if port and token:
                credentials.append((port.group(1), token.group(1)))
        if len(credentials) != 1:
            raise RuntimeError("Expected exactly one running League client with LCU credentials")
        port, token = credentials[0]
        self.base = f"https://127.0.0.1:{port}"
        self.auth = "Basic " + base64.b64encode(f"riot:{token}".encode()).decode()
        # Only loopback requests use this self-signed-certificate context.
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        )

    def request(self, method, path, body=None, live=False):
        url = ("https://127.0.0.1:2999" if live else self.base) + path
        headers = {"Accept": "application/json"}
        if not live:
            headers["Authorization"] = self.auth
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code, method, path, exc.read().decode(errors="replace")) from None

    def phase(self):
        return self.request("GET", "/lol-gameflow/v1/gameflow-phase")


