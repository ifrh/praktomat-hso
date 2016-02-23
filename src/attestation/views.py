from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render_to_response, get_object_or_404
from django.http import HttpResponseRedirect
from django.template.context import RequestContext
from django.core.urlresolvers import reverse
from django.forms.models import modelformset_factory
from django.db.models import Count, Max, Sum
from django.db import transaction
from django.contrib.auth.models import Group
from django.views.decorators.cache import cache_control
from django.http import HttpResponse
from django.template import loader, Context
from django.conf import settings
from collections import Counter
import datetime
import codecs

from tasks.models import Task
from solutions.models import Solution, SolutionFile
from solutions.forms import SolutionFormSet
from checker.basemodels import CheckerResult, check_solution
from attestation.models import Attestation, AnnotatedSolutionFile, RatingResult, Script, RatingScale, RatingScaleItem
from attestation.forms import AnnotatedFileFormSet, RatingResultFormSet, AttestationForm, AttestationPreviewForm, ScriptForm, PublishFinalGradeForm, GenerateRatingScaleForm
from accounts.models import User, Tutorial
from accounts.views import access_denied
from configuration import get_settings


@login_required
def statistics(request,task_id):
	task = get_object_or_404(Task, pk=task_id)
	
	if not (request.user.is_trainer or request.user.is_tutor or request.user.is_superuser):
		return access_denied(request)
	
	final_solutions = task.solution_set.filter(final=True)
	unfinal_solutions = task.solution_set.filter(final=False)
	user = Group.objects.get(name='User').user_set.filter(is_active=True)
	
	tutorials = request.user.tutored_tutorials.all()
        if request.user.is_tutor:
		final_solutions = final_solutions.filter(author__tutorial__in = tutorials)
		unfinal_solutions = unfinal_solutions.filter(author__tutorial__in = tutorials)
		user = User.objects.filter(tutorial__in = tutorials)
		
	final_solution_count = final_solutions.count()
	user_count = user.count()
	
	submissions = []
	submissions_final = []
	acc_submissions = [0]
	creation_dates = map(lambda dict:dict['creation_date'].date(), unfinal_solutions.values('creation_date'))
	creation_dates_final = map(lambda dict:dict['creation_date'].date(), final_solutions.values('creation_date'))
	for date in daterange(task.publication_date.date(), min(task.submission_date.date(), datetime.date.today())):
		submissions.append(creation_dates.count(date))
		submissions_final.append(creation_dates_final.count(date))
		acc_submissions.append(acc_submissions[-1]+submissions_final[-1])
	acc_submissions.pop(0)
	if (user_count > 0):
		acc_submissions = map(lambda submissions: float(submissions)/user_count, acc_submissions)
	else:
		acc_submissions = 0;
	
	creation_times = map(lambda dict:[(dict['creation_date'].time().hour*3600+dict['creation_date'].time().minute*60)*1000, dict['creation_date'].weekday()], unfinal_solutions.values('creation_date'))
	creation_times_final = map(lambda dict:[(dict['creation_date'].time().hour*3600+dict['creation_date'].time().minute*60)*1000, dict['creation_date'].weekday()], final_solutions.values('creation_date'))
	
        if request.user.is_trainer:
		attestations = Attestation.objects.filter(solution__task__id=task.id, final=True, published=False).aggregate(final=Count('id'))
		attestations.update( Attestation.objects.filter(solution__task__id=task.id, final=True, published=True).aggregate(published=Count('id')) )
	else: # Tutor
		attestations = Attestation.objects.filter(solution__task__id=task.id, final=True, published=False, author__tutored_tutorials__in = tutorials).aggregate(final=Count('id'))
		attestations.update( Attestation.objects.filter(solution__task__id=task.id, final=True, published=True, author__tutored_tutorials__in = tutorials).aggregate(published=Count('id')))
		
	attestations['all'] = final_solution_count


	all_items = task.final_grade_rating_scale.ratingscaleitem_set.values_list('name','position')
	final_grade_rating_scale_items = "['" + "','".join([name.strip() for (name,position) in all_items]) + "']"

	all_ratings = []
        if request.user.is_trainer:
		# Each Tutorials ratings
		for t in Tutorial.objects.all():
			all_ratings.append({'title'   : u"Final Grades for Students in Tutorial %s" % unicode(t),
		                        'desc'    : u"This chart shows the distribution of final grades for students from Tutorial %s. Plagiarism is excluded." % unicode(t),
                                'ratings' : RatingScaleItem.objects.filter(attestation__solution__task=task_id, attestation__solution__plagiarism=False, attestation__final=True, attestation__solution__author__tutorial = t)})
   		for t in User.objects.filter(groups__name='Tutor'):
			all_ratings.append({'title'   : u"Final Grades for Attestations created by %s" % unicode(t),
	                            'desc'    : u"This chart shows the distribution of final grades for Attestations created by %s. Plagiarism is excluded." % unicode(t),
                                'ratings' : RatingScaleItem.objects.filter(attestation__solution__task=task_id, attestation__solution__plagiarism=False, attestation__final=True, attestation__author__id = t.id)})
	else:
		# The Tutorials ratings
		all_ratings.append(        {'title'   : u"Final grades (My Tutorials)",
		                            'desc'    : u"This chart shows the distribution of final grades for students from any your tutorials. Plagiarism is excluded.",
                                            'ratings' : RatingScaleItem.objects.filter(attestation__solution__task=task_id, attestation__solution__plagiarism=False, attestation__final=True, attestation__solution__author__tutorial__in = tutorials)})
   		all_ratings.append(        {'title'   : u"Final grades (My Attestations)",
		                            'desc'    : u"This chart shows the distribution of final grades for your attestations. Plagiarism is excluded.",
                                            'ratings' : RatingScaleItem.objects.filter(attestation__solution__task=task_id, attestation__solution__plagiarism=False, attestation__final=True, attestation__author__id = request.user.id)})
	# Overall ratings
	all_ratings.append(                {'title'   : u"Final grades (overall)",
	                                    'desc'    : u"This chart shows the distribution of final grades for all students. Plagiarism is excluded.",
                                            'ratings' : RatingScaleItem.objects.filter(attestation__solution__task=task_id, attestation__solution__plagiarism=False, attestation__final=True)})

	for i,r in enumerate(all_ratings):
		all_ratings[i]['ratings'] = [list(rating) for rating in r['ratings'].annotate(Count('id')).values_list('position','id__count')]

	has_runtimes = False
        runtimes = []
        for i, checker in enumerate(task.get_checkers()):
            checker_runtimes = []
            for result in checker.results.order_by('creation_date').filter(runtime__gt = 0):
		has_runtimes = True
                checker_runtimes.append({ 'date': result.creation_date, 'value': result.runtime})

            if checker_runtimes:
                first = checker_runtimes[0]
                last = checker_runtimes[-1]
                n = 20 # number of buckets
                buckets = [[] for x in range(n)]
                span = last['date'] - first['date'] + datetime.timedelta(seconds=1)
                for r in checker_runtimes:
                    i = timedelta_diff((r['date'] - first['date'])*n, span)
                    buckets[i].append(r['value'])
                medians = []
                for i in range(n):
                    date = first['date'] + ((span//2)*(2*i+1) // n);
                    if buckets[i]:
                        buckets[i].sort()
                        value = buckets[i][((len(buckets[i])+1)/2)-1]
                    else:
                        value = None
                    medians.append({'date': date, 'value': value});

                runtimes.append({
                    'checker': "%d: %s" % (i, checker.title()),
                    'runtimes': checker_runtimes,
                    'medians': medians
                    })

	return render_to_response("attestation/statistics.html",
            {'task':                           task,
            'user_count':                      user_count,
            'solution_count':                  final_solution_count,
            'submissions':                     submissions,
            'submissions_final':               submissions_final,
            'creation_times':                  creation_times,
            'creation_times_final':            creation_times_final,
            'acc_submissions':                 acc_submissions,
            'attestations':                    attestations,
            'final_grade_rating_scale_items':  final_grade_rating_scale_items,
            'all_ratings':                     all_ratings,
            'runtimes':                        runtimes,
            'has_runtime_chart':               has_runtimes,
            }, context_instance=RequestContext(request))

def daterange(start_date, end_date):
    for n in range((end_date - start_date).days + 1):
        yield start_date + datetime.timedelta(n)
	
@login_required
@cache_control(must_revalidate=True, no_cache=True, no_store=True, max_age=0) #reload the page from the server even if the user used the back button
def attestation_list(request, task_id):
	if not (request.user.is_tutor or request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)
	
	task = Task.objects.get(pk=task_id)

	attestation_stats = []
        if request.user.is_trainer:
		attestation_stats =  [ {'tutor': tutor,
        	                        'unattested' : Solution.objects.filter(task = task, final=True, plagiarism = False, attestation = None,author__tutorial__tutors=tutor).count(), 
                	                'final': Attestation.objects.filter(solution__task = task,final=True,author=tutor).count(),
                        	        'nonfinal': Attestation.objects.filter(solution__task = task,final=False,author=tutor).count() }
	                              for tutor in User.objects.filter(groups__name="Tutor")]

		for entry in attestation_stats:
			entry['attested'] = entry['final']+entry['nonfinal']
			entry['total']    = entry['final']+entry['nonfinal']+entry['unattested']


	tutored_users = User.objects.filter(groups__name="User", is_active=True).order_by('last_name') if request.user.is_trainer or request.user.is_superuser else None

	unattested_solutions = Solution.objects.filter(task = task, final=True, plagiarism = False, attestation = None)	
	if request.user.is_tutor: # the trainer sees them all
		unattested_solutions = unattested_solutions.filter(author__tutorial__in = request.user.tutored_tutorials.all())

        all_attestations = Attestation.objects \
                .filter(solution__task = task) \
                .order_by('-created') \
                .select_related('solution', 'solution__author', 'author')

	my_attestations = \
            all_attestations \
            .filter(author = request.user) \

	all_attestations_for_my_tutorials = \
            all_attestations \
            .filter(solution__author__tutorial__in = request.user.tutored_tutorials.all()) \

        attestations_by_others = \
            all_attestations_for_my_tutorials \
            .exclude(author = request.user)

        # for the warning about solutions marked as plagiarism
	if request.user.is_trainer:
		# show all to trainer
		solutions_with_plagiarism = Solution.objects.filter(task = task, plagiarism = True)
	else:
		# show from my turials to tutors
		solutions_with_plagiarism = Solution.objects.filter(task = task, plagiarism = True, author__tutorial__in = request.user.tutored_tutorials.all())

        # the trainer sees all
	if not request.user.is_trainer:
            all_attestations = None

        publishable_tutorial = all_attestations_for_my_tutorials.filter(final = True, published = False)

        publishable_all = None
	if request.user.is_trainer:
            publishable_all = all_attestations.filter(final = True, published = False)

	if request.method == "POST":
            if request.POST['what'] == 'tutorial':
                if not request.user.is_tutor:
                        return access_denied(request)
                if task.only_trainers_publish:
                        return access_denied(request)
                for attestation in publishable_tutorial:
			attestation.publish(request, request.user)
		return HttpResponseRedirect(reverse('attestation_list', args=[task_id]))

            if request.POST['what'] == 'all':
                if not request.user.is_trainer:
                        return access_denied(request)
                for attestation in publishable_all:
			attestation.publish(request, request.user)
		return HttpResponseRedirect(reverse('attestation_list', args=[task_id]))

	show_author = not get_settings().anonymous_attestation or request.user.is_tutor or request.user.is_trainer or published

	data = {'task':task,
		 'tutored_users':tutored_users,
		 'solutions_with_plagiarism':solutions_with_plagiarism,
		 'my_attestations':my_attestations,
		 'attestations_by_others':attestations_by_others,
		 'all_attestations':all_attestations,
		 'unattested_solutions':unattested_solutions,
		 'publishable_tutorial': publishable_tutorial,
		 'publishable_all': publishable_all,
		 'show_author': show_author,
		 'attestation_stats' : attestation_stats}
	return render_to_response("attestation/attestation_list.html", data, context_instance=RequestContext(request))


@login_required
def new_attestation_for_task(request, task_id):
	""" Start an attestation on a restrained random set of my tutored users """
	if not (request.user.is_tutor or request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)
	
	# fetch a solution of a user i have allredy attested in the past.		
	users_i_have_attestated = User.objects.filter(solution__attestation__author = request.user)
	all_available_solutions = Solution.objects.filter(task__id = task_id, final=True, plagiarism = False, author__tutorial__in = request.user.tutored_tutorials.all(), attestation = None)
	if (not all_available_solutions):
		# if an other tutor just grabed the last solution just go back to the list
		return HttpResponseRedirect(reverse('attestation_list', args=[task_id]))
	solutions = all_available_solutions.filter(author__in = users_i_have_attestated)
	if (solutions):
		solution = solutions[0]
	else:
		solution = all_available_solutions[0]

	return new_attestation_for_solution(request, solution.id)


@login_required
@transaction.atomic
def new_attestation_for_solution(request, solution_id, force_create = False):
	if not (request.user.is_tutor or request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)

	solution = get_object_or_404(Solution, pk=solution_id)

	attestations = Attestation.objects.filter(solution = solution)
	if ((not force_create) and attestations):
		return render_to_response("attestation/attestation_already_exists_for_solution.html", { 'task' : solution.task, 'attestations' : attestations, 'solution' : solution, 'show_author': not get_settings().anonymous_attestation }, context_instance=RequestContext(request))

	attest = Attestation(solution = solution, author = request.user)
	attest.save()
	for solutionFile in  solution.solutionfile_set.filter(mime_type__startswith='text'):
		annotatedFile = AnnotatedSolutionFile(attestation = attest, solution_file=solutionFile, content=solutionFile.content())
		annotatedFile.save()
	for rating in solution.task.rating_set.all():
		ratingResult = RatingResult(attestation = attest, rating=rating)
		ratingResult.save()
	return HttpResponseRedirect(reverse('edit_attestation', args=[attest.id]))

@login_required
@transaction.atomic
def withdraw_attestation(request, attestation_id):
	if not (request.user.is_tutor or request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)

	attest = get_object_or_404(Attestation, pk=attestation_id)
        if not (attest.author == request.user or request.user.is_trainer):
		return access_denied(request)

        if attest.solution.task.only_trainers_publish and not request.user.is_trainer:
		return access_denied(request)

	if not attest.published:
		# If if this attestation is already final or not by this user redirect to view_attestation
		return HttpResponseRedirect(reverse('view_attestation', args=[attestation_id]))

	if request.method != "POST":
		return HttpResponseRedirect(reverse('view_attestation', args=[attestation_id]))

	attest.withdraw(request, by=request.user)
	return HttpResponseRedirect(reverse('edit_attestation', args=[attestation_id]))

@login_required	
def edit_attestation(request, attestation_id):
	if not (request.user.is_tutor or request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)
	
	attest = get_object_or_404(Attestation, pk=attestation_id)
        if not (attest.author == request.user or request.user.is_trainer):
		return access_denied(request)
        if attest.published:
		# If if this attestation is already final or not by this user redirect to view_attestation
		return HttpResponseRedirect(reverse('view_attestation', args=[attestation_id]))
	
	solution = attest.solution
	model_solution = solution.task.model_solution

	if request.method == "POST":
            with transaction.atomic():
                    attestForm = AttestationForm(request.POST, instance=attest, prefix='attest')
                    attestFileFormSet = AnnotatedFileFormSet(request.POST, instance=attest, prefix='attestfiles')
                    ratingResultFormSet = RatingResultFormSet(request.POST, instance=attest, prefix='ratingresult')
                    if attestForm.is_valid() and attestFileFormSet.is_valid() and ratingResultFormSet.is_valid():
                            attestForm.save()
                            attest.final = False
                            attest.save()
                            attestFileFormSet.save()
                            ratingResultFormSet.save()
                            return HttpResponseRedirect(reverse('view_attestation', args=[attestation_id]))
	else:
		attestForm = AttestationForm(instance=attest, prefix='attest')
		attestFileFormSet = AnnotatedFileFormSet(instance=attest, prefix='attestfiles')
		ratingResultFormSet = RatingResultFormSet(instance=attest, prefix='ratingresult')
	
	show_author = not get_settings().anonymous_attestation 
	show_run_checkers = get_settings().attestation_allow_run_checkers
	
	return render_to_response("attestation/attestation_edit.html", {"attestForm": attestForm, "attestFileFormSet": attestFileFormSet, "ratingResultFormSet":ratingResultFormSet, "solution": solution, "model_solution":model_solution, "show_author":show_author, "show_run_checkers":show_run_checkers},	context_instance=RequestContext(request))

@login_required	
def view_attestation(request, attestation_id):
	attest = get_object_or_404(Attestation, pk=attestation_id)
        may_modify = attest.author == request.user or request.user.is_trainer
        may_view = attest.solution.author == request.user or request.user.is_tutor or may_modify
        if not may_view:
		return access_denied(request)

	if request.method == "POST":
                if not may_modify:
                        return access_denied(request)
		with transaction.atomic():
			form = AttestationPreviewForm(request.POST, instance=attest)
			if form.is_valid():
				form.save()
				if 'publish' in request.POST:
                                        if attest.solution.task.only_trainers_publish and not request.user.is_trainer:
                                                return access_denied(request)

					attest.publish(request, by = request.user)
				return HttpResponseRedirect(reverse('attestation_list', args=[attest.solution.task.id]))
	else:
		form = AttestationPreviewForm(instance=attest)
		submitable = may_modify and not attest.published
		withdrawable = may_modify and attest.published
                return render_to_response("attestation/attestation_view.html", {"attest": attest, 'submitable':submitable, 'withdrawable': withdrawable, 'form':form, 'show_author': not get_settings().anonymous_attestation, 'show_attestor': not get_settings().invisible_attestor},	context_instance=RequestContext(request))


def user_task_attestation_map(users,tasks,only_published=True):
	if only_published:
		attestations = Attestation.objects.filter( published=True )
	else:
		attestations = Attestation.objects.all()
	
	attestation_dict = {} 	#{(task_id,user_id):attestation}
	for attestation in attestations:
		attestation_dict[attestation.solution.task_id, attestation.solution.author_id] = attestation
	
	task_id_list = tasks.values_list('id', flat=True)
	user_id_list = users.values_list('id', flat=True)
	
	rating_list = []
	for user_id in user_id_list:
		rating_for_user_list = []
		for task_id in task_id_list:
			try:
				rating = attestation_dict[task_id,user_id]
			except KeyError:
				rating = None
			rating_for_user_list.append(rating)
		rating_list.append((User.objects.get(id=user_id),rating_for_user_list))
	
	return rating_list


@login_required	
def rating_overview(request):
	if not (request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)
	
	tasks = Task.objects.filter(submission_date__lt = datetime.datetime.now()).order_by('publication_date','submission_date')
	users = User.objects.filter(groups__name='User').filter(is_active=True).order_by('last_name','first_name')
	rating_list = user_task_attestation_map(users, tasks)
		
	FinalGradeFormSet = modelformset_factory(User, fields=('final_grade',), extra=0)
	# corresponding user to user_id_list in reverse order! important for easy displaying in template
	user = User.objects.filter(groups__name='User').filter(is_active=True).order_by('-last_name','-first_name')
	
	script = Script.objects.get_or_create(id=1)[0]
	
	if request.method == "POST":
		final_grade_formset = FinalGradeFormSet(request.POST, request.FILES, queryset = user)
		script_form = ScriptForm(request.POST, instance=script)
		publish_final_grade_form = PublishFinalGradeForm(request.POST, instance=get_settings())
		if final_grade_formset.is_valid() and script_form.is_valid() and publish_final_grade_form.is_valid():
			final_grade_formset.save()
			script_form.save()
			publish_final_grade_form.save()
	else:
		final_grade_formset = FinalGradeFormSet(queryset = user)
		script_form = ScriptForm(instance=script)
		publish_final_grade_form = PublishFinalGradeForm(instance=get_settings())
	
	return render_to_response("attestation/rating_overview.html", {'rating_list':rating_list, 'tasks':tasks, 'final_grade_formset':final_grade_formset, 'script_form':script_form, 'publish_final_grade_form':publish_final_grade_form},	context_instance=RequestContext(request))

@login_required	
def tutorial_overview(request, tutorial_id=None):
	if not (request.user.is_tutor or request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)
		
	if (tutorial_id):
		tutorial = get_object_or_404(Tutorial, pk=tutorial_id)
		if request.user.is_tutor and not tutorial.tutors.filter(id=request.user.id):
			return access_denied(request)
	else:
		tutorials = request.user.tutored_tutorials.all()
		if (not tutorials):
			return render_to_response("attestation/tutorial_none.html",context_instance=RequestContext(request))
 
		tutorial = request.user.tutored_tutorials.all()[0]

        if request.user.is_tutor:
		other_tutorials = request.user.tutored_tutorials.all()
	else:
		other_tutorials = Tutorial.objects.all()
	other_tutorials = other_tutorials.exclude(id=tutorial.id)
	
	tasks = Task.objects.filter(submission_date__lt = datetime.datetime.now()).order_by('publication_date','submission_date')
	users = User.objects.filter(groups__name='User').filter(is_active=True, tutorial=tutorial).order_by('last_name','first_name')
	rating_list = user_task_attestation_map(users, tasks,False)
	
	def to_float(a,default,const):
		try:
			return (float(str(a.final_grade)),const)
		except (ValueError,TypeError,AttributeError):
			return (default,default)

	averages     = [0.0 for i in range(len(tasks))]
	nr_of_grades = [0 for i in range(len(tasks))]
	for (user,attestations) in rating_list:
		averages     = [avg+to_float(att,0.0,None)[0] for (avg,att) in zip(averages,attestations)]
		nr_of_grades = [n+to_float(att,0,1)[1] for (n,att) in zip(nr_of_grades,attestations)]

	nr_of_grades = [ (n if n>0 else 1) for n in nr_of_grades]

	averages = [a/n for (a,n) in zip(averages,nr_of_grades)]
	script = Script.objects.get_or_create(id=1)[0]
	
	return render_to_response("attestation/tutorial_overview.html", {'other_tutorials':other_tutorials, 'tutorial':tutorial, 'rating_list':rating_list, 'tasks':tasks, 'final_grades_published': get_settings().final_grades_published, 'script':script, 'averages':averages},	context_instance=RequestContext(request))


@login_required	
def rating_export(request):
	if not (request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)
	
	attestations = Attestation.objects.filter(published=True, solution__plagiarism=False)
	
	attestation_dict = {} 	#{(task_id,user_id):rating}
	for attestation in attestations:
			attestation_dict[attestation.solution.task_id, attestation.solution.author_id] = attestation
	
	task_id_list = Task.objects.filter(submission_date__lt = datetime.datetime.now()).order_by('publication_date','submission_date').values_list('id', flat=True)
	user_id_list = User.objects.filter(groups__name='User').filter(is_active=True).order_by('last_name','first_name').values_list('id', flat=True)
	
	task_list = map(lambda task_id:Task.objects.get(id=task_id), task_id_list)	
	
	rating_list = []
	for user_id in user_id_list:
		rating_for_user_list = [User.objects.get(id=user_id)]
		for task_id in task_id_list:
			try:
				rating = attestation_dict[task_id,user_id]
			except KeyError:
				rating = None
			rating_for_user_list.append(rating)
		rating_list.append(rating_for_user_list)
	
	response = HttpResponse(content_type='text/csv')
	response['Content-Disposition'] = 'attachment; rating_export.csv'

	t = loader.get_template('attestation/rating_export.csv')
	c = Context({'rating_list':rating_list, 'task_list':task_list})
	#response.write(u'\ufeff') setting utf-8 BOM for Exel doesn't work
	response.write(t.render(c))
	return response
	
def frange(start, end, inc):
	"A range function, that does accept float increments..."
	L = []
	while 1:
		next = start + len(L) * inc
		if inc > 0 and next > end:
			break
		elif inc < 0 and next < end:
			break
		L.append(next)
	return L

@staff_member_required
def generate_ratingscale(request):
	""" View in the admin """
	if request.method == 'POST': 
		form = GenerateRatingScaleForm(request.POST)		
		if form.is_valid():
			scale = RatingScale(name=form.cleaned_data['name'])
			scale.save()
			start = form.cleaned_data['start']
			end = form.cleaned_data['end']
			step = form.cleaned_data['step']
			count = 0
			for x in frange(start, end, step):
				item = RatingScaleItem(scale=scale, name=x, position=count)
				item.save()
				count += 1
			return HttpResponseRedirect(reverse('admin:attestation_ratingscale_changelist')) 			
	else:
		form = GenerateRatingScaleForm()
	return render_to_response('admin/attestation/ratingscale/generate.html', {'form': form, 'title':"Generate RatingScale"  }, RequestContext(request))



@login_required
def attestation_run_checker(request,attestation_id):
	if not (request.user.is_tutor or request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)

	attestation = get_object_or_404(Attestation, pk=attestation_id)
	if not (attestation.author == request.user or request.user.is_trainer or request.user.is_superuser):
		return access_denied(request)

	if attestation.published:
		return access_denied(request)

	if not get_settings().attestation_allow_run_checkers:
		return access_denied(request)
 


	solution = attestation.solution
	check_solution(solution,True)
	return HttpResponseRedirect(reverse('edit_attestation', args=[attestation_id]))
	
# Can be replaced by // in python 3.2
def timedelta_diff(td1,td2):
    return int(td1.total_seconds() / td2.total_seconds())
