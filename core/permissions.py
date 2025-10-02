from rest_framework import permissions

class IsOwnerOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # For Expense/Income (created_by)
        if hasattr(obj, "created_by"):
            return obj.created_by == request.user or request.user.is_superuser
        # For User
        return obj == request.user or request.user.is_superuser
