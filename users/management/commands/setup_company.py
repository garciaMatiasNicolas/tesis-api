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
        parser.add_argument(
            '--initial',
            action='store_true',
            help='Setup inicial: crea migraciones y migra schema public antes de crear el tenant'
        )
    
    def handle_client_creation(self, options):
        try:
            # Verificar si el tenant ya existe
            if Costumer.objects.filter(schema_name=options['schema_name']).exists():
                self.stdout.write(
                    self.style.ERROR(f'Tenant con schema {options["schema_name"]} ya existe')
                )
                return False

            # Crear el tenant deshabilitando auto-creación
            self.stdout.write('Creando tenant...')
            tenant = Costumer()
            tenant.schema_name = options['schema_name']
            tenant.name = options['company_name']
            tenant.paid_until = '2030-12-31'
            tenant.on_trial = False
            tenant.auto_create_schema = False  # Desactivar creación automática
            tenant.save()
            self.stdout.write(self.style.SUCCESS(f'✓ Tenant guardado'))

            # Crear el dominio
            self.stdout.write(f'Creando dominio {options["domain"]}...')
            domain = Domain()
            domain.domain = options['domain']
            domain.tenant = tenant
            domain.is_primary = True
            domain.save()
            self.stdout.write(self.style.SUCCESS(f'✓ Dominio guardado'))

            # Crear el schema en PostgreSQL manualmente
            self.stdout.write(f'Creando schema PostgreSQL {options["schema_name"]}...')
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS {options["schema_name"]}')
            self.stdout.write(self.style.SUCCESS(f'✓ Schema creado'))

            # Migrar la base de datos para el nuevo tenant manualmente
            self.stdout.write(f'Migrando schema {options["schema_name"]}...')
            call_command('migrate_schemas', '--schema', options['schema_name'])
            
            self.stdout.write(
                self.style.SUCCESS(f'✓ Tenant {options["company_name"]} creado exitosamente')
            )
            return True
            
        except Exception as e:
            import traceback
            self.stdout.write(self.style.ERROR(f'Error creando tenant: {str(e)}'))
            self.stdout.write(self.style.ERROR(traceback.format_exc()))
            return False
    
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
                    return False

                # Crear el superusuario
                User.objects.create_superuser(
                    email=options['admin_email'],
                    password=options['admin_password']
                )
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Superusuario {options["admin_email"]} creado'
                    )
                )
                return True
                
        except Costumer.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Tenant {options["schema_name"]} no encontrado')
            )
            return False
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creando superusuario: {str(e)}')
            )
            return False
    
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
                    return False

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
                        f'✓ Tienda y sucursal creadas'
                    )
                )
                return True
                
        except Costumer.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Tenant {options["schema_name"]} no encontrado')
            )
            return False
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Usuario {options["admin_email"]} no encontrado en este tenant')
            )
            return False
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creando tienda: {str(e)}')
            )
            return False


    def handle_initial_setup(self):
        """Setup inicial: crea migraciones y prepara el schema public"""
        try:
            # 1. Crear migraciones de todas las apps
            self.stdout.write('📝 Creando migraciones...')
            call_command('makemigrations', 'main', 'users', 'store', 'crm', 'stock', 'ecommerce', 'billing', 'audit')
            self.stdout.write(self.style.SUCCESS('✓ Migraciones creadas'))
            
            # 2. Migrar el schema public
            self.stdout.write('🔄 Migrando schema public...')
            call_command('migrate_schemas', '--schema', 'public')
            self.stdout.write(self.style.SUCCESS('✓ Schema public migrado'))
            
            return True
            
        except Exception as e:
            import traceback
            self.stdout.write(self.style.ERROR(f'Error en setup inicial: {str(e)}'))
            self.stdout.write(self.style.ERROR(traceback.format_exc()))
            return False

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('=== Configurando nueva empresa ==='))
        
        # 0. Setup inicial si se especifica el flag
        if options.get('initial'):
            self.stdout.write(self.style.WARNING('\n🚀 MODO INICIAL: Configurando base de datos desde cero\n'))
            if not self.handle_initial_setup():
                self.stdout.write(self.style.ERROR('\n❌ Falló el setup inicial. Abortando.'))
                return
            self.stdout.write('')  # Línea en blanco
        
        # 1. Crear tenant
        self.stdout.write('1️⃣  Creando tenant...')
        if not self.handle_client_creation(options):
            self.stdout.write(self.style.ERROR('\n❌ Falló la creación del tenant. Abortando.'))
            return

        # 2. Crear superusuario
        self.stdout.write('\n2️⃣  Creando superusuario...')
        if not self.handle_superuser_creation(options):
            self.stdout.write(self.style.ERROR('\n❌ Falló la creación del superusuario. Abortando.'))
            return
    
        # 3. Crear tienda principal
        self.stdout.write('\n3️⃣  Creando tienda principal...')
        if not self.handle_store_creation(options):
            self.stdout.write(self.style.ERROR('\n❌ Falló la creación de la tienda. Abortando.'))
            return
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n\n✅ Empresa {options["company_name"]} configurada exitosamente!'
                f'\n📧 Admin: {options["admin_email"]}'
                f'\n🌐 Dominio: {options["domain"]}'
            )
        )