from models import *
from django.core.mail import send_mail
from django.template import Context, RequestContext, loader
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render_to_response, redirect
from crush_connector.models import Person, Crush, RefreshDates, PersonBeenNotified, MutualCrush
from crush_connector.forms import RegisterForm
from datetime import datetime, timedelta
from hash_crushes import crush_digest
from crush.settings import HOSTNAME, HOSTNAME_SSL

def isMatch(Person1, Person2):
    '''Return True if Person2 has already submitted a crush on Person1.
    Call this function when we receive a crush from Person1 on Person2 (crush in the opposite direction), to see if this is a match.
    '''
    digest = crush_digest(Person2, Person1)
    crush_hashes = CrushHash.objects.filter(active=True, digest=digest)
    return len(crush_hashes) > 0

def confirmCrushAndEmail(Person1, Person2):
    if isMatch(Person1, Person2): 
        sendEmail(Person1, Person2)
        return True
    else:
        # if the person has not yet been notified about Crush, then notify them!
        try:
            notified = PersonBeenNotified.objects.get(person=Person2)
        except:
            sendEmailNoMatch(Person2)
            notified = PersonBeenNotified(person=Person2)
            notified.save()
        return False

def sendEmail(Person1, Person2):
    SUBJECT = 'Mutual Crush Found!'
    MESSAGE = "Congratulations " + Person1.name + " and " + Person2.name + ", you both have a crush on each other!"
    EMAILS = [Person1.email, Person2.email]
    FROM = "mit-crush@mit.edu"
    send_mail(SUBJECT, MESSAGE, FROM, EMAILS, fail_silently=False)

def sendEmailNoMatch(Person2):
    SUBJECT = 'An  MIT student has a crush on you'
    MESSAGE = '''Dear %s,

An anonymous MIT student has a crush on you. You can go to crush.mit.edu to find out whether or not this is a mutual crush.

MIT Crush is a way to submit anonymous crushes on people. If a crush is mutual then both people who submitted the anonymous crush are informed that the other person feels the same way.

Good luck,
MIT Crush
''' % Person2.name
    EMAILS = [Person2.email]
    FROM = 'mit-crush@mit.edu'
    send_mail(SUBJECT, MESSAGE, FROM, EMAILS, fail_silently=False)

def sendVerificationEmail(Person):
    SUBJECT = "MIT Crush Verification"
    LINK = "http://18.181.0.46:4040/register?email=%s&key=%s" %(Person.email, Person.SecretKey)
    MESSAGE = "You are receiving this email because you made a crush request on MIT Crush Connector." + LINK  + " If this action was not done by you, please disregard this email and do not click the above link"
    EMAILS = [Person.email]
    FROM = "crush@mit.edu"
    send_mail(SUBJECT, MESSAGE, FROM, EMAILS, fail_silently=False)

def submit(request):
    form = RegisterForm(request.POST)
    if form.is_valid():
        print('form is valid')
        if not 'email' in request.session:
            return redirect('%s/need_certificate' % HOSTNAME)
        person = Person.objects.get(
            email = request.session['email'] 
            )
        num_allowed = person.num_allowed_crushes
        if num_allowed < 0:
            num_allowed = Crush.num_allowed_crushes

        num_submitted = 0
        for i in range(Crush.num_allowed_crushes):
            crush_email = form.cleaned_data['Crush_email_%d' % (i+1)]
            if crush_email != '':
                num_submitted += 1
                try:
                    crush = Person.objects.get(email=crush_email)
                except:
                    variables = RequestContext(request, {
                        'invalid': crush_email
                        })
                    return render_to_response('crush_connector/invalid.html', variables)

        num_left = num_allowed - person.num_crushes_used

        next_refresh = RefreshDates.objects.filter(date__gte = datetime.today()).order_by('date')[0]

        variables = RequestContext(request, {
                'num_left': num_left,
                'num_allowed': num_allowed,
                'num_used': person.num_crushes_used,
                'refresh_date': next_refresh
            })

        crushes = CrushHash.objects.filter(crusher=person)
        if num_submitted > num_left and len(crushes) > 0:
            last_submission = crushes[0].timestamp
            last_refresh = RefreshDates.objects.filter(date__lte = datetime.today()).order_by('-date')[0]
            if last_refresh.date > last_submission.date():
                for crush in crushes:
                    crush.active = False
                    crush.save()
                person.num_crushes_used = 0
            else:
                # too many, not allowed to submit this many crushes
                # throw error page, tell them to go back and submit fewer and wait til refresh date to submit more
                return render_to_response('crush_connector/over_limit.html', variables)

        matches = []
        for i in range(Crush.num_allowed_crushes):
            crush_email = form.cleaned_data['Crush_email_%d' % (i+1)]
            if crush_email == '':
                continue
            crush_person, created = Person.objects.get_or_create(
                email = crush_email
                )
            if created:
                print('creating new person for the crush')
                crush_person.name = '__no_name__  %s' % crush_email
                crush_person.save()
            digest = crush_digest(person, crush_person)
            now = datetime.now()
            crush_hash = CrushHash(crusher=person, digest=digest, timestamp=now)
            crush_hash.save()
            crush = Crush(crusher=person, crushee=crush_person, timestamp=now)
            crush.save()
            person.num_crushes_used += 1
            person.save()
            if confirmCrushAndEmail(person, crush_person):
                print('match! check your email')
                matches.append(crush_person)
                mutual = MutualCrushHash(crush_hash=crush_hash)
                mutual.save()
        num_left = num_left - num_submitted

        variables = RequestContext(request, {
                'num_left': num_left,
                'num_allowed': num_allowed,
                'num_used': person.num_crushes_used,
                'refresh_date': next_refresh
            })

        return render_to_response('crush_connector/validate.html', variables)
    else:        
        variables = RequestContext(request, {'form': form, 'hostname': HOSTNAME})
        return render_to_response('crush_connector/connect.html', variables)

def emailDebug(message):
    SUBJECT = "MIT Crush Debug 5"
    EMAILS = ['blakeelias@gmail.com']
    FROM = "mit-crush@mit.edu"
    send_mail(SUBJECT, message, FROM, EMAILS, fail_silently=False)
    
def index(request):
    return HttpResponseRedirect('%s/auth/' % HOSTNAME_SSL)

def auth(request):
    if not 'REDIRECT_SSL_CLIENT_S_DN_Email' in request.META:
        return redirect('%s/need_certificate' % HOSTNAME)
    person = Person.objects.get(
        email = request.META['REDIRECT_SSL_CLIENT_S_DN_Email'] 
    )

    request.session['email'] = person.email
    request.session['auth'] = True

    return redirect('%s/form/' % HOSTNAME)

def form(request):
    print('at form')
    if 'auth' in request.session and 'email' in request.session:

        form = RegisterForm()
        variables = RequestContext(request, {'form': form, 'hostname': HOSTNAME})

        return render_to_response('crush_connector/connect.html', variables)
    else:

        return redirect('%s/need_certificate' % HOSTNAME)

def about(request):
    return render_to_response('crush_connector/about.html')

def success(request):
    return render_to_response('crush_connector/validate.html')

def getlabels(request):
    matching = quickSearch(request.GET.get('term', 'oawiejfoawiejf'))
    list = "["
    first = True
    for person in matching:
        if (not first):
            list += " , "
        first = False
        list += '{"label": "' + person + '", "value": "' + person.split(" ")[-1] + '"}'
    list += "]"
    return HttpResponse(list)

def clearMiddleNames(request):
    persons = Person.objects.all()
    for person in persons:
        name_list = person.name.split(" ")
        if len(name_list) >= 2:
            person.name = name_list[0] + " " + name_list[-1]
        elif len(name_list) == 1:
            person.name = name_list[0]
        else:
            person.name = "Invalid Name"
        person.save()
    return HttpResponse("Done")

def getEmails(request):
    persons = Person.objects.all()
    list = '['
    first = True
    for person in persons:
        if (not first):
            list += ","
        first = False
        list += '"' + person.email +'"'
    list += ']'
    return HttpResponse(list)
            
def quickSearch(name):
    persons = Person.objects.all()
    list = []
    for person in persons:
        list.append(person.name + " " + person.email)
    matching = [s for s in list if name in s]
    return matching
    
def getnames(request):
    return render_to_response('crush_connector/names.json')

def need_certificate(request):
    return render_to_response('crush_connector/need_certificate.html')

def over_limit(request):
    return render_to_response('crush_connector/over_limit.html', request)

def splash(request):
    return render_to_response('crush_connector/launching_soon.html')

def decoy(request):
    return HttpResponse('0x8739ae05')
