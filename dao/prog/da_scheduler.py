import datetime
import logging
import sys
import time
from subprocess import Popen
from zoneinfo import ZoneInfo

from da_base import DaBase

_LOGGER = logging.getLogger(__name__)


class DaScheduler(DaBase):
    def __init__(self, file_name: str | None = None):
        super().__init__(file_name)
        self.active = self.config.scheduler.active
        self.offset_start = self.config.scheduler.offset or 0
        _LOGGER.info(f"Offset tasks {self.offset_start} sec")
        self.scheduler_tasks = {
            entry.time: entry.action for entry in self.config.scheduler.schedule
        }

    def run_task_process(self, key_task):
        run_task = self.tasks[key_task]
        proc = Popen(run_task["cmd"])
        proc.wait()
        if proc.returncode != 0 and proc.returncode is not None:
            print(f"Task {key_task} crashed with exit code {proc.returncode}")
            return False
        return True

    def scheduler(self):
        # if not (self.notification_entity is None) and self.notification_opstarten:
        #     self.set_value(self.notification_entity, "DAO scheduler gestart " +
        #                    datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S'))
        # Progress on the physical timeline; local minutes can repeat or vanish.
        zone = ZoneInfo(self.time_zone)
        last_minute = None
        while True:
            t = datetime.datetime.now(datetime.UTC)
            _LOGGER.debug(f"Entry loop at {t.astimezone(zone)}")
            next_min = t.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
            if last_minute is not None and next_min <= last_minute:
                time.sleep(max(0, (next_min - t).total_seconds()))
                continue
            last_minute = next_min
            local_min = next_min.astimezone(zone)
            _LOGGER.debug(f"Next minute {local_min}")
            start_at = next_min - datetime.timedelta(seconds=self.offset_start)
            _LOGGER.debug(f"Geplande start at {start_at.astimezone(zone)}")
            time.sleep(max(0, (start_at - t).total_seconds()))
            if not self.active:
                continue
            _LOGGER.debug(f"Gestart op {datetime.datetime.now(datetime.UTC).astimezone(zone)}")
            hour = local_min.hour
            minute = local_min.minute
            key0 = str(hour).zfill(2) + str(minute).zfill(2)
            # ieder uur in dezelfde minuut voorbeeld xx15
            key1 = "xx" + str(minute).zfill(2)
            # iedere minuut in een uur voorbeeld 02xx
            key2 = str(hour).zfill(2) + "xx"
            tasks = []
            for key in self.scheduler_tasks:
                if key == key0 or key == key1 or key == key2:
                    tasks.append(self.scheduler_tasks[key])
            for task in tasks:
                for key_task in self.tasks:
                    if self.tasks[key_task]["function"] == task:
                        try:
                            self.run_task_process(key_task)
                        except KeyboardInterrupt:
                            sys.exit()
                        except Exception as e:
                            print(e)
                            continue
                        break


def main():
    da_sched = DaScheduler("../data/options.json")
    da_sched.scheduler()


if __name__ == "__main__":
    main()
