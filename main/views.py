from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from .models import Job, JobApplication, User
from .serializers import JobSerializer, JobApplicationSerializer, UserSerializer
from django.db.models import Q

class IsEmployerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.user_type == 'EMPLOYER'
    
class UserCreateView(generics.CreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]

class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = User.objects.none()
        user = self.request.user
        
        # Need some improvements on handling requests from different user types.
        
        if user.user_type == 'EMPLOYER':
            # Employers can only see freelancers
            queryset = User.objects.filter(user_type='FREELANCER')
        elif user.user_type == 'FREELANCER':
            # Freelancers can only see employers
            queryset = User.objects.filter(user_type='EMPLOYER')

        user_type = self.request.query_params.get('user_type', None)
        if user_type:
            queryset = queryset.filter(user_type=user_type)

        return queryset.only('id', 'username', 'user_type', 'first_name', 'last_name')

class JobViewSet(viewsets.ModelViewSet):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmployerOrReadOnly]

    # Search jobs by title, description, or category
    def get_queryset(self):
        queryset = Job.objects.all()
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(category__icontains=search)
            )
        return queryset

    def perform_create(self, serializer):
        serializer.save(employer=self.request.user)

class JobApplicationViewSet(viewsets.ModelViewSet):
    queryset = JobApplication.objects.all()
    serializer_class = JobApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.user_type not in ['EMPLOYER', 'FREELANCER']:
            raise ValueError("User must have a valid user type")
            
        if user.user_type == 'EMPLOYER':
            return JobApplication.objects.filter(job__employer=user)
        elif user.user_type == 'FREELANCER':
            return JobApplication.objects.filter(freelancer=user)
        else:
            return JobApplication.objects.none()

    def perform_create(self, serializer):
        job_id = self.request.data.get('job')
        job = get_object_or_404(Job, id=job_id)
        if self.request.user.user_type != 'FREELANCER':
            raise PermissionDenied("Only freelancers can apply for jobs")
        serializer.save(freelancer=self.request.user, job=job)

    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        application = self.get_object()
        if request.user != application.job.employer:
            raise PermissionDenied("Only the job employer can update application status")
        
        new_status = request.data.get('status')
        if new_status not in ['ACCEPTED', 'REJECTED']:
            return Response(
                {'error': 'Invalid status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        application.status = new_status
        application.save()
        return Response({'status': new_status})