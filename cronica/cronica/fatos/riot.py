"""Cliente da Riot API. Sem estado global, chave injetada, cache em disco.

O cache em disco não é otimização: é a diferença entre poder re-rodar o
pipeline à vontade e ter que esperar horas de rate limit a cada mudança de
ideia na camada de cima. Match e timeline são imutáveis, então cachear é
sempre correto.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests

from .. import config


class ErroRiot(Exception):
    pass


class Limitador:
    """Os dois limites da chave de dev: ~20 req/s e 100 req/2min.

    Margem de 95 em vez de 100 porque o relógio local e o da Riot não são o
    mesmo, e um 429 no meio de uma coleta de milhares de partidas custa mais
    que as 5 requisições economizadas.
    """

    def __init__(self, por_2min: int = 95) -> None:
        self.por_2min = por_2min
        self.marcas: list[float] = []

    def esperar(self) -> None:
        agora = time.time()
        self.marcas = [t for t in self.marcas if agora - t < 120]
        if len(self.marcas) >= self.por_2min:
            dorme = 120 - (agora - self.marcas[0]) + 1
            if dorme > 0:
                print(f"   [rate] aguardando {dorme:.0f}s...", flush=True)
                time.sleep(dorme)
        if self.marcas and time.time() - self.marcas[-1] < 0.06:
            time.sleep(0.06)
        self.marcas.append(time.time())


class ClienteRiot:
    def __init__(self, api_key: Optional[str] = None,
                 regional: Optional[str] = None,
                 cache: Optional[Path] = None) -> None:
        self.api_key = api_key or config.RIOT_API_KEY
        if not self.api_key:
            raise ErroRiot(
                "RIOT_API_KEY ausente. Defina no ambiente ou no .env — "
                "nunca no código nem em arquivo versionado.")
        self.regional = regional or config.RIOT_REGIONAL
        self.cache = Path(cache) if cache else config.DIR_CACHE
        self.cache.mkdir(parents=True, exist_ok=True)
        self.lim = Limitador()

    def _get(self, url: str, params: Optional[dict] = None, tentativas: int = 4):
        headers = {"X-Riot-Token": self.api_key}
        for i in range(tentativas):
            self.lim.esperar()
            r = requests.get(url, headers=headers, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                espera = int(r.headers.get("Retry-After", "10"))
                print(f"   [429] dormindo {espera}s...", flush=True)
                time.sleep(espera + 1)
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 * (i + 1))
                continue
            if r.status_code in (401, 403):
                raise ErroRiot(
                    f"{r.status_code} — chave inválida ou expirada. "
                    "Chave de DEV vale 24h; coleta longa exige chave de produção.")
            if r.status_code == 404:
                return None
            print(f"   [HTTP {r.status_code}] {url}", flush=True)
            time.sleep(2)
        return None

    def _cacheado(self, nome: str, url: str):
        arq = self.cache / nome
        if arq.exists():
            try:
                return json.loads(arq.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                arq.unlink(missing_ok=True)   # cache corrompido: refaz
        dados = self._get(url)
        if dados:
            arq.write_text(json.dumps(dados), encoding="utf-8")
        return dados

    # ---- endpoints ----
    def puuid(self, nome: str, tag: str) -> Optional[str]:
        url = (f"https://{self.regional}.api.riotgames.com/riot/account/v1/"
               f"accounts/by-riot-id/{requests.utils.quote(nome)}/"
               f"{requests.utils.quote(tag)}")
        d = self._get(url)
        return d.get("puuid") if d else None

    def ids_de_partida(self, puuid: str, fila: Optional[int] = None,
                       maximo: int = 1000) -> list[str]:
        """Pagina o histórico inteiro disponível (a Riot devolve 100 por vez)."""
        ids: list[str] = []
        while len(ids) < maximo:
            params = {"start": len(ids), "count": min(100, maximo - len(ids))}
            if fila is not None:
                params["queue"] = fila
            url = (f"https://{self.regional}.api.riotgames.com/lol/match/v5/"
                   f"matches/by-puuid/{puuid}/ids")
            lote = self._get(url, params=params) or []
            if not lote:
                break
            ids.extend(lote)
            if len(lote) < params["count"]:
                break
        return ids

    def partida(self, match_id: str) -> Optional[dict]:
        return self._cacheado(
            f"{match_id}.json",
            f"https://{self.regional}.api.riotgames.com/lol/match/v5/matches/{match_id}")

    def timeline(self, match_id: str) -> Optional[dict]:
        return self._cacheado(
            f"{match_id}_timeline.json",
            f"https://{self.regional}.api.riotgames.com/lol/match/v5/"
            f"matches/{match_id}/timeline")
