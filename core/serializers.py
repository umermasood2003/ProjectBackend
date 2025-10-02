from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import Role, User, Expense, Income

# 1. Role Serializer
class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'name']

# 2. Me Serializer
class MeSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "role"]

# 3. User Serializer
class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(),
        source='role',
        write_only=True,
        required=False   # ✅ make optional for signup
    )

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'role', 'role_id','gmail','gmail_app_password']
        extra_kwargs = {'password': {'write_only': True, 'required': True}}

    def create(self, validated_data):
        # Hash password before saving
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save()
        return instance


class ExpenseSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id',
            'transaction_id',
            'transaction_type',
            'sender_name',
            'receiver_name',
            'amount',
            'fee',
            'total',
            'date_time',
            'created_by',
        ]
        read_only_fields = ['created_by']

# 5. Income Serializer
class IncomeSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Income
        fields = ['id', 'title', 'amount', 'source', 'date', 'created_by']


