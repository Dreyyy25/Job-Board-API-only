from django.db import models


class SeekerProfileQuerySet(models.QuerySet):
    def with_related(self):
        # SeekerProfile.user_account is the PK (OneToOne, primary_key=True).
        # select_related still pays off when views access profile.user_account.email.
        # Prefetch reverse FKs on UserAccount — education/experiences/skills are
        # related to UserAccount, not SeekerProfile.
        return self.select_related('user_account').prefetch_related(
            'user_account__education',
            'user_account__experiences',
            'user_account__skills__skill_set',
        )


class EducationDataQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user_account=user)

    def with_related(self):
        return self.select_related('user_account')


class ExperienceDataQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user_account=user)

    def with_related(self):
        return self.select_related('user_account')


class SeekerSkillSetQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user_account=user)

    def with_related(self):
        return self.select_related('user_account', 'skill_set')
