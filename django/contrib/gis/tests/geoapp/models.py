from django.contrib.gis.db import models
from django.contrib.gis.tests.utils import mysql

# MySQL spatial indices can't handle NULL geometries.
null_flag = not mysql

class Country(models.Model):
    name = models.CharField(max_length=30)
    mpoly = models.MultiPolygonField() # SRID, by default, is 4326
    objects = models.GeoManager()

class City(models.Model):
    name = models.CharField(max_length=30)
    point = models.PointField() 
    objects = models.GeoManager()

class State(models.Model):
    name = models.CharField(max_length=30)
    poly = models.PolygonField(null=null_flag) # Allowing NULL geometries here.
    objects = models.GeoManager()

class Feature(models.Model):
    name = models.CharField(max_length=20)
    geom = models.GeometryField()
    objects = models.GeoManager()