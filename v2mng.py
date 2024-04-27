from typing import Any
import logging

logger = logging.getLogger("v2mng")
logging.basicConfig(level="INFO")


def base64_decode(data: str | bytes) -> str:
    import base64

    return base64.b64decode(data).decode()


def json_load(path):
    import json

    with open(path) as f:
        return json.load(f)


def json_dump(obj, path):
    import json

    with open(path, "w") as f:
        json.dump(obj, f)


## subs
# v2rayn: https://github.com/2dust/v2rayN/wiki/分享链接格式说明(ver-2)


def v2rayn_parse(data: bytes) -> dict[str, dict[str, Any]]:
    settings: dict[str, dict[str, Any]] = dict()
    urls: list[str] = base64_decode(data).splitlines()
    for url in urls:
        if not url.startswith("vmess://"):
            logger.warning("invalid url scheme %s", url)
        else:
            try:
                ps, setting = vmess_parse(url)
                settings[ps] = setting
            except Exception:
                logger.warning("invalid vmess url %s", url, exc_info=True)
    return settings


def vmess_parse(url: str) -> tuple[str, dict[str, Any]]:
    import types, json

    data: dict[str, str] = base64_decode(url.removeprefix("vmess://"))
    d = types.SimpleNamespace(**json.loads(data))
    if d.v != "2":
        raise RuntimeError("invalid v", d.v)
    if hasattr(d, "scy") and d.scy and d.scy != "none":
        raise RuntimeError("invalid scy", d.scy)
    if hasattr(d, "type") and d.type and d.type != "none":
        raise RuntimeError("invalid type", d.type)

    vmess_settings = {
        "vnext": [{"address": d.add, "port": int(d.port), "users": [{"id": d.id}]}]
    }

    stream_settings = {}
    if hasattr(d, "tls") and d.tls:
        match d.tls:
            case "tls":
                stream_settings["security"] = "tls"
                tls_settings = {}
                if hasattr(d, "sni"):
                    tls_settings["serverName"] = d.sni
                if hasattr(d, "alpn"):
                    tls_settings["alpn"] = d.alpn.split(",")
                if tls_settings:
                    stream_settings["tlsSettings"] = tls_settings
            case _:
                raise RuntimeError("invalid tls", tls)
    if hasattr(d, "net") and d.net:
        match d.net:
            case "ws":
                stream_settings["network"] = "ws"
                ws_settings = {}
                if hasattr(d, "path") and d.path:
                    ws_settings["path"] = d.path
                if hasattr(d, "host") and d.host:
                    ws_settings["headers"] = {"Host": d.host}
                if ws_settings:
                    stream_settings["wsSettings"] = ws_settings
            case _:
                raise RuntimeError("invalid net", d.net)

    return d.ps, {
        "protocol": "vmess",
        "settings": vmess_settings,
        "streamSettings": stream_settings,
    }


def v2rayn_fetch_1(path: str) -> dict[str, dict[str, Any]]:
    import requests

    data: bytes
    if path.startswith("http://") or path.startswith("https://"):
        logger.info("retrieve subscribe from network")
        resp = requests.get(path)
        if resp.status_code != 200:
            resp.raise_for_status()
            raise RuntimeError("invalid http status", resp.status_code, resp.reason)
        data = resp.content
    else:
        logger.info("retrieve subscribe from local")
        with open(path, "rb") as f:
            data = f.read()
    return v2rayn_parse(data)


def v2rayn_fetch(paths) -> list[tuple[str, dict[str, Any]]]:
    settings: list[tuple[str, dict[str, Any]]] = list()
    for i, path in enumerate(paths):
        try:
            _settings = v2rayn_fetch_1(path)
        except Exception:
            logger.warning("fetch failed %s", path, exc_info=True)
        else:
            for ps, setting in _settings.items():
                settings.append((f"{i}_{ps}", setting))
    return settings


## cli

default_skel = {
    "inbounds": [{"port": 1080, "protocol": "socks"}],
    "outbounds": [None, {"protocol": "freedom", "tag": "direct"}],
    "routing": {
        "domainStrategy": "IPOnDemand",
        "rules": [
            {
                "type": "field",
                "ip": ["geoip:cn", "geoip:private"],
                "outboundTag": "direct",
            }
        ],
    },
}


class CLI:
    path: str

    def __init__(self, path="~/.v2mng"):
        import pathlib

        self.path = pathlib.Path(path).expanduser()

    @property
    def subs_in_path(self) -> str:
        return self.path / "subs.in.json"

    @property
    def subs_path(self) -> str:
        return self.path / "subs.json"

    @property
    def skel_path(self) -> str:
        return self.path / "skel.json"

    @property
    def config_path(self) -> str:
        return self.path / "config.json"

    @property
    def exec_path(self) -> str:
        return self.path / "v2ray" / "v2ray"

    @property
    def subs_in(self) -> list[str]:
        return json_load(self.subs_in_path)

    @property
    def subs(self) -> list[tuple[str, dict[str, Any]]]:
        return json_load(self.subs_path)

    @property
    def skel(self) -> dict[str, Any]:
        skel_path = self.skel_path
        if skel_path.exists():
            return json_load(skel_path)
        else:
            return default_skel

    def fetch(self):
        paths = self.subs_in
        settings = v2rayn_fetch(paths)
        json_dump(settings, self.subs_path)

    def gen(self):
        import copy

        i = int(input("select: "))
        name, setting = self.subs[i]
        config = copy.deepcopy(self.skel)
        config["outbounds"][0] = setting
        json_dump(config, self.config_path)

    def list(self):
        for i, (name, setting) in enumerate(self.subs):
            print(i, name, setting.get("streamSettings"))

    def test(self):
        import os

        os.system("{} test -c {}".format(self.exec_path, self.config_path))

    def run(self):
        import os

        os.system("{} run -c {}".format(self.exec_path, self.config_path))


## main


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--path", default="~/.v2mng")
    parser.add_argument("cmd")
    args = parser.parse_args()
    cli = CLI(args.path)
    match args.cmd:
        case "l":
            cli.list()
        case "f":
            cli.fetch()
        case "g":
            cli.list()
            cli.gen()
        case "t":
            cli.test()
        case "r":
            cli.run()
        case _:
            raise RuntimeError("invalid cmd", args.cmd)


if __name__ == "__main__":
    main()
