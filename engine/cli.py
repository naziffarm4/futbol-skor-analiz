"""Terminal üzerinden veri toplama ve skor tahmin motorunu çalıştıran CLI arayüzü."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.bulletin import export_bulletin_file
from engine.config import LeagueId, Settings
from engine.runner import run_full_cycle

logger = logging.getLogger(__name__)


def _resolve_interval_seconds() -> float:
    raw_hours = os.getenv("SYNC_INTERVAL_HOURS", "24").strip()
    try:
        hours = float(raw_hours)
        if hours <= 0:
            raise ValueError
    except ValueError:
        hours = 24.0
    return hours * 3600.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engine.cli",
        description="Futbol haftalık fikstür, sakatlık, skor tahmini ve analiz CLI aracı.",
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--league",
        choices=[lid.value for lid in LeagueId],
        default=None,
        help="Yalnızca belirtilen ligi çalıştırır.",
    )
    target_group.add_argument(
        "--all",
        action="store_true",
        help="Desteklenen 4 ligin tamamını sırayla çalıştırır.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Supabase'e yazmadan yerel JSON ve özet çıktısı üretir.",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Belirli aralıklarla (varsayılan: 24 saat) otonom zamanlayıcı döngüsünde çalışır.",
    )
    parser.add_argument(
        "--export-bulletin",
        type=Path,
        default=None,
        metavar="OUTPUT_PATH",
        help="4 ligin haftalık bültenini GET /api/v1/bulletin şemasında hedef JSON dosyasına atomik olarak yazar.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = parse_args(argv)
    target_leagues = [LeagueId(args.league)] if args.league else None
    persist = not args.dry_run

    if args.export_bulletin is not None:
        cfg = Settings.from_env()
        export_persist = persist and bool(
            cfg.supabase_url and cfg.resolve_api_key(use_service_role=True)
        )
        cycle = run_full_cycle(
            leagues=target_leagues,
            persist=export_persist,
            only_next_round=True,
        )
        bulletin = export_bulletin_file(cycle, args.export_bulletin)
        total_matches = int(bulletin.get("total_matches", 0))
        print(
            json.dumps(
                {
                    "status": cycle.status,
                    "output_path": str(args.export_bulletin),
                    "generated_at": bulletin.get("generated_at"),
                    "total_matches": total_matches,
                    "total_played_matches": int(bulletin.get("total_played_matches", 0)),
                    "total_injuries": int(bulletin.get("total_injuries", 0)),
                    "leagues_count": len(bulletin.get("leagues", ())),
                    "errors": cycle.errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if total_matches > 0 else 1

    if not args.schedule:
        result = run_full_cycle(leagues=target_leagues, persist=persist)
        print(result.to_json(include_records=args.dry_run))
        return 0 if result.status != "error" else 1

    interval_seconds = _resolve_interval_seconds()
    logger.info(
        "Zamanlayıcı modu başlatıldı (aralık: %.1f saat, persist=%s).",
        interval_seconds / 3600.0,
        persist,
    )
    try:
        while True:
            result = run_full_cycle(leagues=target_leagues, persist=persist)
            print(result.to_json(include_records=False), flush=True)
            logger.info("Sonraki döngü için %.0f saniye bekleniyor...", interval_seconds)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("Zamanlayıcı kullanıcı tarafından durduruldu.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
