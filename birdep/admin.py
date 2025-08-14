# birdep/admin.py
from django.contrib import admin
from .models import BirDep, Program, Fungsionaris, PengurusInti

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
    list_display = ['nama', 'nama_panjang', 'logo_filename', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['nama', 'nama_panjang', 'tentang_deskripsi']
    prepopulated_fields = {'slug': ('nama',)}
    inlines = [ProgramInline, FungsionarisInline]
    
    fieldsets = (
        ('Informasi Dasar', {
            'fields': ('nama', 'nama_panjang', 'slug', 'logo_filename', 'is_active')
        }),
        ('Halaman Tentang', {
            'fields': ('tentang_deskripsi', 'visi', 'misi'),
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

@admin.register(PengurusInti)
class PengurusIntiAdmin(admin.ModelAdmin):
    list_display = ['nama', 'jabatan', 'urutan', 'is_active']
    list_filter = ['jabatan', 'is_active']
    search_fields = ['nama', 'ikhtisar']
    list_editable = ['urutan', 'is_active']
    prepopulated_fields = {'slug': ('jabatan',)}
    
    fieldsets = (
        ('Informasi Personal', {
            'fields': ('nama', 'jabatan', 'slug', 'foto')
        }),
        ('Konten', {
            'fields': ('ikhtisar', 'deskripsi_kerja')
        }),
        ('Pengaturan', {
            'fields': ('urutan', 'is_active')
        }),
    )