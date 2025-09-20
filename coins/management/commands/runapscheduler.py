from django.conf import settings

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution
from django_apscheduler import util
from coins.models import Coin
from coins.services import get_supported_coin_list, SUPPORTED_COINS_TIMEOUT
import logging


@util.close_old_connections
def save_new_supported_coins():
    coin_list = get_supported_coin_list()
    coin_objs = [
        Coin(cg_id=coin["id"], name=coin["name"], symbol=coin["symbol"])
        for coin in coin_list
    ]
    Coin.objects.bulk_create(coin_objs, ignore_conflicts=True)


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
    def add_arguments(self, parser):
        parser.add_argument(
            "--run-now",
            action="store_true",
            help="Run the coin update task immediately before starting the scheduler.",
        )

    def handle(self, *args, **options):
        logger = logging.getLogger(__name__)
        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_jobstore(DjangoJobStore(), "default")

        minutes = SUPPORTED_COINS_TIMEOUT + 60 * 5  # add 5 minutes to get fresh
        scheduler.add_job(
            save_new_supported_coins,
            "interval",
            minutes=minutes,
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

        if options.get("run_now"):
            logger.info("--run-now provided: Running coin update task immediately.")
            save_new_supported_coins()
        logger.info("Starting APScheduler...")
        scheduler.start()
