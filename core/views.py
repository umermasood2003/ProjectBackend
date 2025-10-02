from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Sum
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.conf import settings
from zoneinfo import ZoneInfo
import imaplib, email, re, datetime
from bs4 import BeautifulSoup
from django.http import HttpResponse
import openpyxl

from .models import Role, User, Expense, Income
from .serializers import (
    MeSerializer, RoleSerializer, UserSerializer,
    ExpenseSerializer, IncomeSerializer
)
from .permissions import IsOwnerOrAdmin

# 1. Authentication (/auth/me)
class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = MeSerializer(request.user)
        return Response(serializer.data)


# 2. User & Role Management
class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]  # Admin only


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action in ["update", "partial_update", "destroy", "retrieve"]:
            return [IsOwnerOrAdmin()]   # user manages self, admin manages all
        elif self.action == "list":
            return [permissions.IsAdminUser()]  # admin can list all users
        elif self.action == "create":
            return [permissions.AllowAny()]  # signup
        else:
            return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        if "role" not in serializer.validated_data:
            default_role, _ = Role.objects.get_or_create(name="user")
            serializer.save(role=default_role)
        else:
            serializer.save()


# 3. Expenses
class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_queryset(self):
        user = self.request.user
        qs = Expense.objects.filter(created_by=user).order_by("-date_time")

        # Date filtering
        from_date = self.request.query_params.get("from_date")
        to_date = self.request.query_params.get("to_date")

        if from_date:
            qs = qs.filter(date_time__date__gte=from_date)
        if to_date:
            qs = qs.filter(date_time__date__lte=to_date)

        return qs

    @action(detail=False, methods=["post"])
    def fetch_from_gmail(self, request):
        try:
            # ✅ Get Gmail and App Password from logged-in user
            EMAIL = request.user.gmail
            PASSWORD = request.user.gmail_app_password

            if not EMAIL or not PASSWORD:
                return Response(
                    {"error": "Your Gmail or App Password is not set in your profile."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            from_date = request.GET.get("from_date")
            to_date = request.GET.get("to_date")

            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(EMAIL, PASSWORD)
            imap.select("inbox")

            search_query = '(FROM "e.statement@telenorbank.pk")'

            if from_date and to_date:
                from_dt = datetime.datetime.strptime(from_date, "%Y-%m-%d")
                to_dt = datetime.datetime.strptime(to_date, "%Y-%m-%d") + datetime.timedelta(days=1)
                search_query = f'(FROM "e.statement@telenorbank.pk" SINCE {from_dt.strftime("%d-%b-%Y")} BEFORE {to_dt.strftime("%d-%b-%Y")})'
            elif from_date:
                from_dt = datetime.datetime.strptime(from_date, "%Y-%m-%d")
                search_query = f'(FROM "e.statement@telenorbank.pk" SINCE {from_dt.strftime("%d-%b-%Y")})'
            elif to_date:
                to_dt = datetime.datetime.strptime(to_date, "%Y-%m-%d") + datetime.timedelta(days=1)
                search_query = f'(FROM "e.statement@telenorbank.pk" BEFORE {to_dt.strftime("%d-%b-%Y")})'

            status_, messages = imap.search(None, search_query)
            mail_ids = messages[0].split()

            if not mail_ids:
                return Response({"message": "No Easypaisa emails found."}, status=status.HTTP_200_OK)

            imported_ids = []

            for mail_id in reversed(mail_ids):
                status_, data = imap.fetch(mail_id, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        if ctype == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                        elif ctype == "text/html":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")

                soup = BeautifulSoup(body, "html.parser")
                text = soup.get_text(separator="\n")

                transaction_id = None
                amount = fee = total = None
                receiver_name = sender_name = transaction_type = None
                date_time = datetime.datetime.now(tz=ZoneInfo("Asia/Karachi"))

                m = re.search(r"Transaction ID\s+(\d+)", text)
                if m:
                    transaction_id = m.group(1).strip()
                    if Expense.objects.filter(transaction_id=transaction_id).exists():
                        continue

                m = re.search(r"Transaction Type\s+([A-Za-z ]+)", text)
                if m:
                    transaction_type = m.group(1).strip()

                m = re.search(r"Date & Time\s+([0-9]{2}-[A-Za-z]{3}-[0-9]{4}\s+[0-9:]+)", text)
                if m:
                    try:
                        naive_dt = datetime.datetime.strptime(m.group(1).strip(), "%d-%b-%Y %H:%M:%S")
                        date_time = naive_dt.replace(tzinfo=ZoneInfo("Asia/Karachi"))
                    except Exception:
                        pass

                m = re.search(r"Account Title\s+(.+)", text)
                if m:
                    receiver_name = m.group(1).strip()

                m = re.search(r"Sender Name\s+(.+)", text)
                if m:
                    sender_name = m.group(1).strip()

                m = re.search(r"Transfer amount\s+Rs\.?\s*([0-9,\.]+)", text)
                if m:
                    amount = float(m.group(1).replace(",", ""))

                m = re.search(r"Fee\s+Rs\.?\s*([0-9,\.]+)", text)
                if m:
                    fee = float(m.group(1).replace(",", ""))

                m = re.search(r"Total\s+Rs\.?\s*([0-9,\.]+)", text)
                if m:
                    total = float(m.group(1).replace(",", ""))

                if not amount:
                    continue

                try:
                    expense = Expense.objects.create(
                        receiver_name=receiver_name or transaction_type,
                        amount=amount,
                        date_time=date_time,
                        transaction_id=transaction_id or f"mail-{mail_id.decode()}",
                        transaction_type=transaction_type or "Unknown",
                        sender_name=sender_name or "Unknown",
                        fee=fee or 0.0,
                        total=total or amount,
                        created_by=request.user,
                    )
                    imported_ids.append(expense.id)
                except Exception as db_err:
                    print("DB ERROR:", db_err)

            imap.close()
            imap.logout()

            if not imported_ids:
                return Response({"message": "No new valid transactions found."}, status=status.HTTP_200_OK)

            return Response(
                {"message": f"{len(imported_ids)} expenses imported.", "ids": imported_ids},
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            print("GENERAL ERROR:", e)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# 4. Incomes
class IncomeViewSet(viewsets.ModelViewSet):
    serializer_class = IncomeSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        return Income.objects.filter(created_by=user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# 5. Reports
class ReportsViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _filter_queryset(self, qs, request):
        # Allow admin to see all, restrict normal user
        if not request.user.is_superuser:
            qs = qs.filter(created_by=request.user)

        # Month filter
        month = request.query_params.get("month")
        if month:
            try:
                year, mon = map(int, month.split("-"))
                date_field = "date_time" if hasattr(qs.model, "date_time") else "date"
                qs = qs.filter(**{f"{date_field}__year": year, f"{date_field}__month": mon})
            except ValueError:
                return qs.none()
        return qs

    @action(detail=False, methods=["get"])
    def profit_loss(self, request):
        expenses = self._filter_queryset(Expense.objects.all(), request)
        incomes = self._filter_queryset(Income.objects.all(), request)

        total_expenses = expenses.aggregate(total=Sum("amount"))["total"] or 0
        total_income = incomes.aggregate(total=Sum("amount"))["total"] or 0
        profit_loss = total_income - total_expenses

        return Response({
            "total_income": total_income,
            "total_expenses": total_expenses,
            "profit_loss": profit_loss
        })

    @action(detail=False, methods=["get"])
    def type_breakdown(self, request):
        expenses = self._filter_queryset(Expense.objects.all(), request)
        breakdown = (
            expenses.values("transaction_type")
            .annotate(total=Sum("amount"))
            .order_by("transaction_type")
        )
        return Response(breakdown)

    @action(detail=False, methods=["get"])
    def top_expenses(self, request):
        limit = int(request.query_params.get("limit", 5))
        expenses = self._filter_queryset(Expense.objects.all(), request)
        top_expenses = expenses.order_by("-amount")[:limit]
        data = top_expenses.values("transaction_type", "amount", "date_time", "receiver_name")
        return Response(data)

    @action(detail=False, methods=["get"])
    def export_excel(self, request):
        expenses = self._filter_queryset(Expense.objects.all(), request)
        incomes = self._filter_queryset(Income.objects.all(), request)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Financial Report"
        ws.append(["Type/Source", "Category", "Amount", "Date"])

        for exp in expenses:
            ws.append([exp.transaction_type, "Expense", float(exp.amount), exp.date_time.strftime("%Y-%m-%d")])
        for inc in incomes:
            ws.append([inc.source, "Income", float(inc.amount), inc.date.strftime("%Y-%m-%d")])

        total_expenses = expenses.aggregate(total=Sum("amount"))["total"] or 0
        total_income = incomes.aggregate(total=Sum("amount"))["total"] or 0
        profit_loss = total_income - total_expenses

        ws.append([])
        ws.append(["Total Income", total_income])
        ws.append(["Total Expenses", total_expenses])
        ws.append(["Profit/Loss", profit_loss])

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="financial_report.xlsx"'
        wb.save(response)
        return response


# 6. Password Reset
class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]  # anyone can request reset

    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "If the email exists, a reset link has been sent."},
                            status=status.HTTP_200_OK)

        token = default_token_generator.make_token(user)
        reset_url = f"http://localhost:3000/reset-password/{token}/{user.pk}/"

        send_mail(
            subject="Password Reset",
            message=f"Click the link to reset your password: {reset_url}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )

        return Response({"message": "Password reset email sent!"}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]  # anyone with valid token

    def post(self, request):
        token = request.data.get("token")
        uid = request.data.get("uid")
        new_password = request.data.get("new_password")

        if not all([token, uid, new_password]):
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(pk=uid)
        except User.DoesNotExist:
            return Response({"error": "Invalid user"}, status=status.HTTP_400_BAD_REQUEST)

        if not default_token_generator.check_token(user, token):
            return Response({"error": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()

        return Response({"message": "Password has been reset successfully!"}, status=status.HTTP_200_OK)
