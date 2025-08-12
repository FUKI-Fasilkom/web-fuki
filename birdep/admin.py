from django.contrib import admin
from .models import BirDep, Program, Fungsionaris

class ProgramInline(admin.TabularInline):
    model = Program
    extra = 1
    fields = ['judul', 'deskripsi', 'urutan', 'is_active']

class FungsionarisInline(admin.TabularInline):
    model = Fungsionaris
    extra = 1
    fields = ['nama', 'jabatan', 'foto', 'urutan', 'is_active']


@admin.register(BirDep)
class BirDepAdmin(admin.ModelAdmin):
    list_display = ['nama', 'logo_filename', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['nama', 'tentang_deskripsi']  
    prepopulated_fields = {'slug': ('nama',)}  
    inlines = [ProgramInline, FungsionarisInline]
    
    fieldsets = (
        ('Informasi Dasar', {
            'fields': ('nama', 'slug', 'logo_filename', 'is_active')  
        }),
        ('Halaman Tentang', {
            'fields': ('tentang_deskripsi', 'tugas', 'tanggung_jawab'),
            'classes': ('collapse',)  
        }),
    )

@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ['judul', 'birdep', 'urutan', 'is_active']
    list_filter = ['birdep', 'is_active', 'created_at']  
    search_fields = ['judul', 'deskripsi']
    list_editable = ['urutan', 'is_active']  
    
    fieldsets = (
        ('Informasi Program', {
            'fields': ('birdep', 'judul', 'deskripsi')  
        }),
        ('Pengaturan', {
            'fields': ('urutan', 'is_active') 
        }),
    )

@admin.register(Fungsionaris)
class FungsionarisAdmin(admin.ModelAdmin):
    list_display = ['nama', 'jabatan', 'birdep', 'urutan', 'is_active']
    list_filter = ['birdep', 'jabatan', 'is_active']
    search_fields = ['nama', 'jabatan']
    list_editable = ['urutan', 'is_active'] 
    
    fieldsets = (
        ('Informasi Personal', {
            'fields': ('birdep', 'nama', 'jabatan', 'foto')  
        }),
        ('Pengaturan', {
            'fields': ('urutan', 'is_active') 
        }),
    )