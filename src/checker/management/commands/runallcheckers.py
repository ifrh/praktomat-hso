from django.core.management.base import BaseCommand
from tasks.models import Task

class Command(BaseCommand):
    help = 'Run all checkers for expired tasks where not all checkers are finished.'

    def handle(self, *args, **options):
        for task in Task.objects:
            if not task.expired():
                continue
            if not task.all_checker_finished:
                self.stdout.write('Running all checkers for "%s"\n' % task.title)
                task.check_all_final_solutions()
                task.check_all_latest_only_failed_solutions()
            else:
                self.stdout.write('Running all checkers for unchecked solutions in "%s"\n' % task.title)
                task.check_unchecked_final_solutions()
        self.stdout.write('Done')
