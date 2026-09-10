from .models import LeaveRequest, Notification

def admin_notifications(request):
    notifications_count = 0
    if request.user.is_authenticated and hasattr(request.user, 'employee') and request.user.employee.is_company_admin:
        notifications_count += LeaveRequest.objects.filter(status='Pending').count()
    return {'admin_notifications_count': notifications_count}

def global_notifications(request):
    if request.user.is_authenticated:
        unread_notifications = Notification.objects.filter(user=request.user, is_read=False).order_by('-created_at')
        all_notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:10]
        return {
            'user_notifications': all_notifications,
            'unread_notifications_count': unread_notifications.count()
        }
    return {}
