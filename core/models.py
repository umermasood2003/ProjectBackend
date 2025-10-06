import datetime
from django.db import models
from django.contrib.auth.models import AbstractUser

# 1. Custom User Model
class User(AbstractUser):
    role = models.ForeignKey("Role", on_delete=models.CASCADE,null=True, blank=True)
    gmail = models.EmailField(null=True, blank=True)
    gmail_app_password = models.CharField(max_length=100, null=True, blank=True)
    def __str__(self):
        return f"{self.username} ({self.role})" if self.role else self.username

# 2. Role Model
class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    def __str__(self):
        return self.name

# 3. Expense Model
class Expense(models.Model):
    transaction_id = models.CharField(max_length=50, unique=True)
    transaction_type = models.CharField(max_length=100)
    sender_name = models.CharField(max_length=100, blank=True, null=True)
    receiver_name = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    date_time = models.DateTimeField(default=datetime.datetime.now)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="expenses")
    def __str__(self):
        return f"{self.transaction_type} - {self.amount}"

# 4. Income Model
class Income(models.Model):
    title = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    source = models.CharField(max_length=50)
    date = models.DateField(default=datetime.date.today)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="income")
    def __str__(self):
        return f"{self.title} - {self.amount}"

