from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
# from rest_framework.exceptions import PermissionDenied, ValidationError
# from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from .models import Job, JobApplication, User
from .serializers import JobSerializer, JobApplicationSerializer, UserSerializer
from django.db.models import Q

class IsEmployerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        # Allow admin/superuser full access
        if request.user.is_superuser or request.user.is_staff:
            return True
        # Read-only for others, write for employers
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
        try:
            queryset = User.objects.none()
            user = self.request.user
            
            if user.is_superuser:
                queryset = User.objects.all()
                user_type = self.request.query_params.get('user_type')
                if user_type:
                    queryset = queryset.filter(user_type=user_type)
            else:
                queryset = User.objects.filter(id=user.id)

            return queryset.only(
                'id', 'username', 'user_type', 
                'first_name', 'last_name'
            )
            
        except Exception as e:
            return Response({
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            
            if not (request.user.is_superuser or request.user.is_staff):
                return Response({
                    'status': 'error',
                    'message': 'Only administrators can delete user accounts'
                }, status=status.HTTP_403_FORBIDDEN)
            
            instance.delete()
            return Response({
                'status': 'success',
                'message': f'User {instance.username} deleted successfully'
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

class JobViewSet(viewsets.ModelViewSet):
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmployerOrReadOnly]

    def get_queryset(self):
        try:
            queryset = Job.objects.all()
            user = self.request.user

            # Admin
            if user.is_superuser or user.is_staff:
                pass
            # Employers
            elif user.user_type == 'EMPLOYER':
                queryset = queryset.filter(employer=user)
            # Freelancers
            elif user.user_type == 'FREELANCER':
                pass
            else:
                queryset = Job.objects.none()

            search = self.request.query_params.get('search')
            if search:
                queryset = queryset.filter(
                    Q(title__icontains=search) |
                    Q(description__icontains=search) |
                    Q(category__icontains=search)
                )
            
            return queryset.select_related('employer')
            
        except Exception as e:
            return Response({
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    def perform_create(self, serializer):
        try:
            job = serializer.save(employer=self.request.user)
            
            return Response({
                'message': 'Job created successfully',
                'data': JobSerializer(job).data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        
    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            self.perform_destroy(instance)
            return Response({
                'status': 'success',
                'message': 'Job deleted successfully'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

class JobApplicationViewSet(viewsets.ModelViewSet):
    serializer_class = JobApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if user.is_superuser or user.is_staff:
            return JobApplication.objects.all()
        
        if user.user_type not in ['EMPLOYER', 'FREELANCER']:
            raise ValueError("User must have a valid user type")
            
        if user.user_type == 'EMPLOYER':
            return JobApplication.objects.filter(job__employer=user)
        elif user.user_type == 'FREELANCER':
            return JobApplication.objects.filter(freelancer=user)
        else:
            return JobApplication.objects.none()

    def perform_create(self, serializer):
        try:
            job_id = self.request.data.get('job')
            job = get_object_or_404(Job, id=job_id)
            
            if self.request.user.user_type != 'FREELANCER':
                return Response({
                    'message': 'Only freelancers can apply for jobs'
                }, status=status.HTTP_403_FORBIDDEN)
            
            if JobApplication.objects.filter(
                freelancer=self.request.user, 
                job=job
            ).exists():
                return Response({
                    'message': 'You have already applied for this job'
                }, status=status.HTTP_400_BAD_REQUEST)

            application = serializer.save(
                freelancer=self.request.user, 
                job=job
            )
            
            return Response({
                'message': 'Application submitted successfully',
                'data': JobApplicationSerializer(application).data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    def update_status(self, request, pk=None):
        try:
            application = self.get_object()

            # Allow admin to update status
            if not (request.user.is_superuser or 
                   request.user.is_staff or 
                   request.user == application.job.employer):
                return Response({
                    'message': 'Only the job employer or admin can update application status'
                }, status=status.HTTP_403_FORBIDDEN)
            
            new_status = request.data.get('status')
            if new_status not in ['ACCEPTED', 'REJECTED']:
                return Response({
                    'message': "Status must be 'ACCEPTED' or 'REJECTED'"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            application.status = new_status
            application.save()
            
            return Response({
                'message': f'Application status updated to {new_status}',
                'data': {
                    'application_id': str(application.id),
                    'status': new_status
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
                
            self.perform_destroy(instance)
            return Response({
                'status': 'success',
                'message': 'Application withdrawn successfully'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)