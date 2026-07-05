import logging

from django.core.management.base import BaseCommand

from coins.exceptions import CoinGeckoError
from coins.sync import log_sync_result, sync_supported_coins
from common.utils import log_coingecko_failure

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync CoinGecko's supported coin catalog once and exit."

    def handle(self, *args, **options):
        try:
            result = sync_supported_coins()
        except CoinGeckoError as exc:
            log_coingecko_failure(logger, exc)
            return

        log_sync_result(logger, result)
