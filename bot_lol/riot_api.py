"""Cliente da Riot API — reutilizável (sem estado global).

Reaproveita a lógica testada do flex-analyzer.py (rate limit, retry em
429/5xx, cache em disco), mas a chave é injetada e o cache é configurável,
pra servir tanto ao bot 24/7 quanto a scripts pontuais.

Roteamento: BR usa REGIONAL='americas' para account-v1 e match-v5.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests

from . import config


class RateLimiter:
    """Respeita os dois limites da chave de dev (20 req/s e 100 req/2min)."""

    def __init__(self) -> None:
        self.times: list[float] = []

    def wait(self) -> None:
        now = time.time()
        self.times = [t for t in self.times if now - t < 120]
        if len(self.times) >= 95:  # margem sob o limite de 100/2min
            sleep_for = 120 - (now - self.times[0]) + 1
            if sleep_for > 0:
                print(f"   [rate] aguardando {sleep_for:.0f}s (limite 2min)...")
                time.sleep(sleep_for)
        if self.times and now - self.times[-1] < 0.06:  # ~20 req/s
            time.sleep(0.06)
        self.times.append(time.time())


class RiotAPIError(Exception):
    pass


class RiotClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        regional: Optional[str] = None,
        cache_dir: Optional[Path] = None,
    ) -> None:
        self.api_key = api_key or config.RIOT_API_KEY
        if not self.api_key:
            raise RiotAPIError("RIOT_API_KEY ausente (defina no .env ou env var).")
        self.regional = regional or config.RIOT_REGIONAL
        self.cache_dir = Path(cache_dir) if cache_dir else config.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rl = RateLimiter()

    # ---- HTTP base -----------------------------------------------------
    def _get(self, url: str, params: Optional[dict] = None, tries: int = 4):
        headers = {"X-Riot-Token": self.api_key}
        for attempt in range(tries):
            self.rl.wait()
            r = requests.get(url, headers=headers, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", "10"))
                print(f"   [429] rate limit, dormindo {retry}s...")
                time.sleep(retry + 1)
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 401:
                raise RiotAPIError("401 — chave inválida ou expirada (dev expira em 24h).")
            if r.status_code == 404:
                return None
            print(f"   [HTTP {r.status_code}] {url} -> {r.text[:200]}")
            time.sleep(2)
        return None

    # ---- Endpoints -----------------------------------------------------
    def get_puuid(self, game_name: str, tag_line: str) -> Optional[str]:
        url = (f"https://{self.regional}.api.riotgames.com/riot/account/v1/"
               f"accounts/by-riot-id/{game_name}/{tag_line}")
        data = self._get(url)
        return data.get("puuid") if data else None

    def get_match_ids(self, puuid: str, count: int = 20, queue: Optional[int] = None,
                      start: int = 0) -> list[str]:
        """IDs de partida (mais recentes primeiro). queue=440 filtra só Flex."""
        params: dict = {"start": start, "count": min(100, count)}
        if queue is not None:
            params["queue"] = queue
        url = (f"https://{self.regional}.api.riotgames.com/lol/match/v5/"
               f"matches/by-puuid/{puuid}/ids")
        return self._get(url, params=params) or []

    def get_match_ids_all(self, puuid: str, max_total: int = 1000,
                          queue: Optional[int] = None) -> list[str]:
        """Pagina todo o histórico disponível (até max_total)."""
        ids: list[str] = []
        while len(ids) < max_total:
            lote = self.get_match_ids(puuid, count=100, queue=queue, start=len(ids))
            if not lote:
                break
            ids.extend(lote)
            if len(lote) < 100:
                break
        return ids

    def get_match(self, match_id: str) -> Optional[dict]:
        """Partida com cache em disco (re-rodar não recobra da API)."""
        cache_file = self.cache_dir / f"{match_id}.json"
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        url = f"https://{self.regional}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        data = self._get(url)
        if data:
            cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data

    def get_timeline(self, match_id: str) -> Optional[dict]:
        """Timeline (minuto-a-minuto) com cache em disco separado."""
        cache_file = self.cache_dir / f"{match_id}_timeline.json"
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        url = (f"https://{self.regional}.api.riotgames.com/lol/match/v5/"
               f"matches/{match_id}/timeline")
        data = self._get(url)
        if data:
            cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data
