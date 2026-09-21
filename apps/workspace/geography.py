"""Bounded, cached access to public IBGE geography. Never sends campaign data."""

import gzip
import io
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.core.cache import cache


class GeographyUnavailable(Exception):
    pass


BASE = "https://servicodados.ibge.gov.br/api/"
MAX_BYTES = 5 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Refuse before any redirected network request, even to another HTTPS host.
        raise GeographyUnavailable("Redirecionamento da fonte recusado.")


def open_geography(request):
    return build_opener(NoRedirect()).open(request, timeout=10)


def provider_path(kind, code):
    if kind == "catalogo" and code == "BR":
        return "v1/localidades/estados?orderBy=nome"
    if kind == "municipios" and re.fullmatch(r"[1-5][0-9]", code):
        return f"v1/localidades/estados/{code}/municipios?orderBy=nome"
    if kind == "distritos" and re.fullmatch(r"[1-5][0-9]{6}", code):
        return f"v1/localidades/municipios/{code}/distritos?orderBy=nome"
    if kind == "limites":
        parameters = "?formato=application/vnd.geo+json&qualidade=minima"
        if code == "BR":
            return "v3/malhas/paises/BR" + parameters + "&intrarregiao=UF"
        if re.fullmatch(r"[1-5][0-9]", code):
            return f"v3/malhas/estados/{code}" + parameters + "&intrarregiao=municipio"
        if re.fullmatch(r"[1-5][0-9]{6}", code):
            return f"v3/malhas/municipios/{code}" + parameters
    raise ValueError("Camada geográfica inválida.")


def public_geography(kind, code):
    path = provider_path(kind, code)
    key = f"ibge-geography:v1:{kind}:{code}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    request = Request(
        BASE + path,
        headers={
            "Accept": "application/json, application/vnd.geo+json",
            "User-Agent": "NabioElege/1.0 (public geographic reference)",
        },
    )
    try:
        with open_geography(request) as response:
            if not response.geturl().startswith(BASE):
                raise GeographyUnavailable
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise GeographyUnavailable
        # The provider may return gzip even when urllib requested identity.
        # Bound decoded bytes too; unbounded decompression is not safe here.
        if body.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                body = compressed.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise GeographyUnavailable
        data = json.loads(body)
        if kind == "limites":
            if (
                not isinstance(data, dict)
                or data.get("type") != "FeatureCollection"
                or not isinstance(data.get("features"), list)
            ):
                raise GeographyUnavailable
            # Drop provider properties unrelated to public boundary identifiers.
            data = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": item["geometry"],
                        "properties": {
                            "codarea": str(
                                item.get("properties", {}).get("codarea", "")
                            )
                        },
                    }
                    for item in data["features"]
                ],
            }
        else:
            if not isinstance(data, list):
                raise GeographyUnavailable
            data = [
                {
                    "id": str(item["id"]),
                    "name": item["nome"],
                    **(
                        {
                            "uf": item["sigla"],
                            "region_id": str(item["regiao"]["id"]),
                            "region": item["regiao"]["nome"],
                        }
                        if kind == "catalogo"
                        else {}
                    ),
                }
                for item in data
            ]
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        EOFError,
    ) as exc:
        raise GeographyUnavailable(
            "A fonte geográfica está temporariamente indisponível."
        ) from exc
    result = {
        "source": "IBGE · API de Localidades e Malhas simplificadas",
        "source_url": BASE + path,
        "data": data,
    }
    cache.set(key, result, timeout=24 * 60 * 60)
    return result
