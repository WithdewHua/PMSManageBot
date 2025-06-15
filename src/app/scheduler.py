from app.utils import SingletonMeta
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler


class Scheduler(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self.jobstores = {
            "default": MemoryJobStore(),
        }
        self.executors = {
            "default": AsyncIOExecutor(),
            "threadpool": ThreadPoolExecutor(100),
        }
        self.scheduler = AsyncIOScheduler(
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

    def add_async_job(self, func, *args, executor="default", **kwargs):
        """添加异步任务，默认使用AsyncIOExecutor"""
        return self.scheduler.add_job(func, *args, executor=executor, **kwargs)

    def add_sync_job(self, func, *args, executor="threadpool", **kwargs):
        """添加同步任务，使用ThreadPoolExecutor"""
        return self.scheduler.add_job(func, *args, executor=executor, **kwargs)

    def remove_job(self, job_id, jobstore=None):
        """移除任务"""
        self.scheduler.remove_job(job_id, jobstore=jobstore)

    def get_jobs(self, jobstore=None):
        """获取所有任务"""
        return self.scheduler.get_jobs(jobstore=jobstore)

    def pause_job(self, job_id, jobstore=None):
        """暂停任务"""
        self.scheduler.pause_job(job_id, jobstore=jobstore)

    def resume_job(self, job_id, jobstore=None):
        """恢复任务"""
        self.scheduler.resume_job(job_id, jobstore=jobstore)
