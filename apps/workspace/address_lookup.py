"""Bounded, cached lookup of public postal references; no campaign/person data."""

import hashlib
import json
import re
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.core.cache import cache

UF_CODES = dict(
    zip(
        "RO AC AM RR PA AP TO MA PI CE RN PB PE AL SE BA MG ES RJ SP PR SC RS MS MT GO DF".split(),
        "11 12 13 14 15 16 17 21 22 23 24 25 26 27 28 29 31 32 33 35 41 42 43 50 51 52 53".split(),
    )
)
BASE = "https://viacep.com.br/ws/"
MAX_BYTES = 96 * 1024


class AddressUnavailable(Exception):
    pass


class NoAddressRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AddressUnavailable


def open_address(request):
    return build_opener(NoAddressRedirect()).open(request, timeout=5)


def query_path(payload):
    if not isinstance(payload, dict):
        raise ValueError
    if set(payload) == {"cep"} and isinstance(payload["cep"], str):
        if not re.fullmatch(r"[0-9]{5}-?[0-9]{3}", payload["cep"].strip()):
            raise ValueError
        return payload["cep"].strip().replace("-", "") + "/json/"
    if set(payload) != {"state", "city", "street"}:
        raise ValueError
    state = payload["state"]
    if not isinstance(state, str) or state not in UF_CODES:
        raise ValueError
    parts = []
    for key in ("city", "street"):
        value = payload[key]
        if not isinstance(value, str) or not 3 <= len(value.strip()) <= 100:
            raise ValueError
        value = " ".join(value.split())
        if (
            not re.fullmatch(r"[^\W_][\w .’'\-]*", value, flags=re.UNICODE)
            or ".." in value
        ):
            raise ValueError
        parts.append(quote(value, safe=""))
    return f"{state}/{parts[0]}/{parts[1]}/json/"


def lookup_address(payload):
    path = query_path(payload)
    key = "postal-reference:v1:" + hashlib.sha256(path.encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    request = Request(
        BASE + path,
        headers={
            "Accept": "application/json",
            "User-Agent": "NabioElege/1.0 (public postal reference)",
        },
    )
    try:
        with open_address(request) as response:
            if response.geturl() != BASE + path:
                raise AddressUnavailable
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise AddressUnavailable
        source = json.loads(body)
        if isinstance(source, dict):
            source = [] if source.get("erro") in (True, "true") else [source]
        if not isinstance(source, list) or len(source) > 50:
            raise AddressUnavailable
        data = []
        for row in source:
            item = {
                key: row.get(provider_key, "")
                for key, provider_key in {
                    "cep": "cep",
                    "street": "logradouro",
                    "neighborhood": "bairro",
                    "city": "localidade",
                    "state": "uf",
                    "ibge": "ibge",
                }.items()
            }
            if not all(
                isinstance(value, str) and len(value) <= 150 for value in item.values()
            ):
                raise AddressUnavailable
            if (
                item["state"] not in UF_CODES
                or not item["city"]
                or not re.fullmatch(r"[0-9]{5}-?[0-9]{3}", item["cep"])
            ):
                raise AddressUnavailable
            if item["ibge"] and (
                not re.fullmatch(r"[0-9]{7}", item["ibge"])
                or not item["ibge"].startswith(UF_CODES[item["state"]])
            ):
                raise AddressUnavailable
            data.append(item)
    except (
        URLError,
        OSError,
        TimeoutError,
        ValueError,
        TypeError,
        AttributeError,
    ) as exc:
        raise AddressUnavailable from exc
    result = {"source": "ViaCEP", "data": data}
    cache.set(key, result, timeout=86400 if data else 900)
    return result
