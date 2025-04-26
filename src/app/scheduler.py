from app.utils import SingletonMeta
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler


class Scheduler(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self.jobstores = {
            "default": MemoryJobStore(),
        }
        self.executors = {"default": ThreadPoolExecutor(100)}
        self.scheduler = BackgroundScheduler(
            jobstores=self.jobstores, executors=self.executors
        )

        self.start()

    def start(self):
        self.scheduler.start()

    def shutdown(self):
        self.scheduler.shutdown()

    def add_jobstore(self, jobstore, alias, **kwargs):
        self.jobstores.update({alias: jobstore})
        self.scheduler.add_jobstore(jobstore, alias=alias, **kwargs)

    def add_job(self, *args, **kwargs):
        self.scheduler.add_job(*args, **kwargs)
