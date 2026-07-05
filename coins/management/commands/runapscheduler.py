import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.core.management.base import BaseCommand
from django_apscheduler import util
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution

from coins.exceptions import CoinGeckoError
from coins.services import SUPPORTED_COINS_TIMEOUT
from coins.sync import log_sync_result, sync_supported_coins
from common.utils import log_coingecko_failure

logger = logging.getLogger(__name__)

SUPPORTED_COINS_SYNC_INTERVAL_SECONDS = SUPPORTED_COINS_TIMEOUT + 5 * 60


@util.close_old_connections
def sync_supported_coins_job():
    try:
        result = sync_supported_coins()
    except CoinGeckoError as exc:
        # Never crash the blocking scheduler on an API failure; skip this run
        # and try again on the next interval.
        log_coingecko_failure(logger, exc)
        return

    log_sync_result(logger, result)


@util.close_old_connections
def delete_old_job_executions(max_age=604_800):
    """
    This job deletes APScheduler job execution entries older than `max_age` from the database.
    It helps to prevent the database from filling up with old historical records that are no
    longer useful.

    :param max_age: The maximum length of time to retain historical job execution records.
                    Defaults to 7 days.
    """
    DjangoJobExecution.objects.delete_old_job_executions(max_age)


class Command(BaseCommand):
    help = "Start APScheduler and run recurring jobs."

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_jobstore(DjangoJobStore(), "default")

        scheduler.add_job(
            sync_supported_coins_job,
            "interval",
            seconds=SUPPORTED_COINS_SYNC_INTERVAL_SECONDS,
            id="save_new_supported_coins",
            max_instances=1,
            replace_existing=True,
        )

        scheduler.add_job(
            delete_old_job_executions,
            trigger=CronTrigger(
                day_of_week="mon", hour="00", minute="00"
            ),  # midnight on monday, before start of the next work week.
            id="delete_old_job_executions",
            max_instances=1,
            replace_existing=True,
        )

        logger.info("Starting APScheduler...")
        scheduler.start()
