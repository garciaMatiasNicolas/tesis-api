from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django_tenants.utils import tenant_context
from main.models import Costumer, Domain
from core.store.models import Store, Branch
User = get_user_model()

class Command(BaseCommand):
    help = 'Crea una empresa completa con tenant y superusuario'

    def add_arguments(self, parser):
        parser.add_argument('company_name', type=str, help='Nombre de la empresa')
        parser.add_argument('schema_name', type=str, help='Schema name (sin espacios)')
        parser.add_argument('domain', type=str, help='Dominio (ej: empresa1.localhost)')
        parser.add_argument('admin_email', type=str, help='Email del admin')
        parser.add_argument('admin_password', type=str, help='Password del admin')
    
    def handle_client_creation(self, options):
        try:
            # Verificar si el tenant ya existe
            if Costumer.objects.filter(schema_name=options['schema_name']).exists():
                self.stdout.write(
                    self.style.ERROR(f'Tenant con schema {options["schema_name"]} ya existe')
                )
                return

            # Crear el tenant
            tenant = Costumer()
            tenant.schema_name = options['schema_name']
            tenant.name = options['company_name']
            tenant.paid_until = '2030-12-31'  # Fecha lejana
            tenant.on_trial = False
            tenant.save()

            # Crear el dominio
            domain = Domain()
            domain.domain = options['domain']
            domain.tenant = tenant
            domain.is_primary = True
            domain.save()

            # Migrar la base de datos para el nuevo tenant
            self.stdout.write(f'Creando schema para {options["schema_name"]}...')
            call_command('makemigrations', 'users', 'store', 'crm', 'stock', 'ecommerce', 'billing', 'audit')
            call_command('migrate')
            call_command('migrate_schemas', '--schema', options['schema_name'])
            
            self.stdout.write(
                self.style.SUCCESS(f'Tenant {options["company_name"]} creado exitosamente')
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creando tenant: {str(e)}')
            )
    
    def handle_superuser_creation(self, options):
        try:
            # Buscar el tenant
            tenant = Costumer.objects.get(schema_name=options['schema_name'])
            
            # Cambiar al contexto del tenant
            with tenant_context(tenant):
                # Verificar si el usuario ya existe
                if User.objects.filter(email=options['admin_email']).exists():
                    self.stdout.write(
                        self.style.ERROR(f'Usuario {options["admin_email"]} ya existe en este tenant')
                    )
                    return

                # Crear el superusuario
                User.objects.create_superuser(
                    email=options['admin_email'],
                    password=options['admin_password']
                )
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Superusuario {options["admin_email"]} creado para tenant {options["schema_name"]}'
                    )
                )
                
        except Costumer.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Tenant {options["schema_name"]} no encontrado')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creando superusuario: {str(e)}')
            )
    
    def handle_store_creation(self, options):
        try:
            # Buscar el tenant
            tenant = Costumer.objects.get(schema_name=options['schema_name'])
            
            # Cambiar al contexto del tenant
            with tenant_context(tenant):
                # Verificar si ya existe una tienda
                if Store.objects.exists():
                    self.stdout.write(
                        self.style.ERROR(f'Ya existe una tienda en este tenant')
                    )
                    return

                # Crear la tienda principal
                store = Store.objects.create(
                    name=f"{options['company_name']}",
                    owner=User.objects.get(email=options['admin_email']),
                    country="",
                    state="",
                    postal_code="",
                    city="",
                    address="",
                    phone="",
                )
                
                # Crear la sucursal principal automáticamente
                Branch.objects.create(
                    store=store,
                    manager=store.owner,
                    name=f"{store.name} - Sucursal Principal",
                    country=store.country,
                    state=store.state,
                    postal_code=store.postal_code,
                    city=store.city,
                    address=store.address
                )
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Tienda {store.name} creada para tenant {options["schema_name"]}'
                    )
                )
                
        except Costumer.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Tenant {options["schema_name"]} no encontrado')
            )
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Usuario {options["admin_email"]} no encontrado en este tenant')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creando tienda: {str(e)}')
            )


    def handle(self, *args, **options):
        self.stdout.write('=== Configurando nueva empresa ===')
        
        # 1. Crear tenant
        self.stdout.write('1. Creando tenant...')
        self.handle_client_creation(options)

        # 2. Crear superusuario
        self.stdout.write('2. Creando superusuario...')
        self.handle_superuser_creation(options)
    
        # 3. Crear tienda principal
        self.stdout.write('3. Creando tienda principal...')
        self.handle_store_creation(options)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Empresa {options["company_name"]} configurada exitosamente!'
                f'\n📧 Admin: {options["admin_email"]}'
                f'\n🌐 Dominio: {options["domain"]}'
            )
        )