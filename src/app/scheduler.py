from app.config import settings
from app.utils.utils import SingletonMeta
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler


class Scheduler(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self.jobstores = {
            "default": MemoryJobStore(),
            "sqlalchemy": SQLAlchemyJobStore(url=settings.DB_URL),
        }
        self.executors = {
            "default": AsyncIOExecutor(),
            "threadpool": ThreadPoolExecutor(100),
        }
        # 配置调度器参数
        job_defaults = {
            "coalesce": True,  # 合并错过的任务
            "max_instances": 1,  # 每个任务最多同时运行1个实例
            "misfire_grace_time": 60,  # 任务最多可以延迟60秒执行
        }
        self.scheduler = AsyncIOScheduler(
            jobstores=self.jobstores,
            executors=self.executors,
            job_defaults=job_defaults,
            timezone=settings.TZ,
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

    def add_async_job(
        self, func, *args, jobstore="default", executor="default", **kwargs
    ):
        """添加异步任务，默认使用AsyncIOExecutor"""
        return self.scheduler.add_job(
            func, *args, jobstore=jobstore, executor=executor, **kwargs
        )

    def add_sync_job(
        self, func, *args, jobstore="default", executor="threadpool", **kwargs
    ):
        """添加同步任务，使用ThreadPoolExecutor"""
        return self.scheduler.add_job(
            func, *args, jobstore=jobstore, executor=executor, **kwargs
        )

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
