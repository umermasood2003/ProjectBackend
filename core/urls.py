from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PasswordResetConfirmView, PasswordResetRequestView, RoleViewSet, UserViewSet, ExpenseViewSet, IncomeViewSet,
     MeView, ReportsViewSet
)

router = DefaultRouter()
router.register(r'roles', RoleViewSet,basename="roles")
router.register(r'users', UserViewSet,basename="users")
router.register(r'expenses', ExpenseViewSet, basename="expenses")
router.register(r'incomes', IncomeViewSet, basename="incomes")
router.register(r'reports', ReportsViewSet, basename="reports")

urlpatterns = [
    path('', include(router.urls)),
    path('auth/me/', MeView.as_view(), name='me'),
    path('api-auth/', include('rest_framework.urls')),
    path("password_reset/", PasswordResetRequestView.as_view(), name="password_reset"),
    path("password_reset/confirm/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
]