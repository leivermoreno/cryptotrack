from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render
from django.urls import reverse

from common.utils import build_query_string, get_safe_redirect_url


def _get_safe_next(request):
    if request.method == "POST" and REDIRECT_FIELD_NAME in request.POST:
        redirect_to = request.POST.get(REDIRECT_FIELD_NAME)
    else:
        redirect_to = request.GET.get(REDIRECT_FIELD_NAME)
    return get_safe_redirect_url(request, redirect_to)


class LoginView(auth_views.LoginView):
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["register_next"] = _get_safe_next(self.request)
        return context


def register(request):
    if request.user.is_authenticated:
        return redirect("coins:index")

    safe_next = _get_safe_next(request)

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request, "Your account has been created. You can now log in."
            )
            login_url = reverse("accounts:login")
            if safe_next:
                query_string = build_query_string({REDIRECT_FIELD_NAME: safe_next})
                login_url = f"{login_url}?{query_string}"
            return redirect(login_url)
    else:
        form = UserCreationForm()
    return render(
        request,
        "registration/register.html",
        {"form": form, REDIRECT_FIELD_NAME: safe_next},
    )
