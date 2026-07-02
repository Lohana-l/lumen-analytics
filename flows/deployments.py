"""Crée et sert les deployments Prefect pour les flows Cairn.

Usage (dans le conteneur flows, après que le serveur Prefect soit up) :
    python -m flows.deployments
"""
from __future__ import annotations

from prefect import serve

from flows.flows import daily_refresh, intraday_predict


def main() -> None:
    daily = daily_refresh.to_deployment(
        name="cairn-daily",
        cron="0 2 * * *",                 # tous les jours à 02:00
        tags=["cairn", "daily"],
        parameters={"accounts": 2_000},
    )
    intraday = intraday_predict.to_deployment(
        name="cairn-intraday",
        cron="0 */2 * * *",               # toutes les 2 heures
        tags=["cairn", "intraday"],
    )
    serve(daily, intraday)


if __name__ == "__main__":
    main()
