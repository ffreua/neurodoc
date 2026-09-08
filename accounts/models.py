import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower

from base.models import TimestampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('email'), name='accounts_user_email_lower_uniq'),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        super().save(*args, **kwargs)

    def get_full_name(self):
        full_name = f'{self.first_name} {self.last_name}'.strip()
        return full_name or self.email

    def get_short_name(self):
        return self.first_name or self.email


class RecoveryCode(TimestampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recovery_codes')
    code_hash = models.CharField(max_length=255)
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)


class PhysicianProfile(TimestampedModel):
    class VerificationStatus(models.TextChoices):
        # Rótulos em português: aparecem na tela da equipe, onde o
        # responsável decide sobre o registro. Os valores gravados seguem
        # em inglês, como o resto do esquema.
        PENDING = 'pending', 'Aguardando validação'
        VERIFIED = 'verified', 'Validado'
        REJECTED = 'rejected', 'Recusado'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='physician_profile')
    professional_name = models.CharField(max_length=255)
    crm_number = models.CharField(max_length=20)
    crm_state = models.CharField(max_length=2)
    rqe = models.CharField(max_length=20, blank=True)
    professional_phone = models.CharField(max_length=16, blank=True)
    professional_email = models.EmailField(max_length=254, blank=True)
    professional_address = models.CharField(max_length=255, blank=True)
    verification_status = models.CharField(
        max_length=40, choices=VerificationStatus.choices, default=VerificationStatus.PENDING,
    )
    #: Quem conferiu o CRM e quando.
    #:
    #: A validação é ato do responsável pela clínica, e numa clínica com um
    #: médico só esse médico é o próprio responsável — ele valida a si
    #: mesmo. Não dá para impedir sem inviabilizar o consultório solo, então
    #: o que resta é deixar registrado, e à vista: a tela mostra quem
    #: liberou a assinatura e em que data. Auditoria em log responde depois;
    #: isto responde na hora de olhar a equipe.
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_note = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['crm_number', 'crm_state'], name='accounts_physicianprofile_crm_uniq'),
        ]

    def __str__(self):
        return f'{self.professional_name} (CRM {self.crm_number}/{self.crm_state})'
