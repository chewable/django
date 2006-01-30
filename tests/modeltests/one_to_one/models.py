"""
10. One-to-one relationships

To define a one-to-one relationship, use ``OneToOneField()``.

In this example, a ``Place`` optionally can be a ``Restaurant``.
"""

from django.db import models

class Place(models.Model):
    name = models.CharField(maxlength=50)
    address = models.CharField(maxlength=80)

    def __repr__(self):
        return "%s the place" % self.name

class Restaurant(models.Model):
    place = models.OneToOneField(Place)
    serves_hot_dogs = models.BooleanField()
    serves_pizza = models.BooleanField()

    def __repr__(self):
        return "%s the restaurant" % self.get_place().name

class Waiter(models.Model):
    restaurant = models.ForeignKey(Restaurant)
    name = models.CharField(maxlength=50)

    def __repr__(self):
        return "%s the waiter at %r" % (self.name, self.get_restaurant())

API_TESTS = """
# Create a couple of Places.
>>> p1 = Place(name='Demon Dogs', address='944 W. Fullerton')
>>> p1.save()
>>> p2 = Place(name='Ace Hardware', address='1013 N. Ashland')
>>> p2.save()

# Create a Restaurant. Pass the ID of the "parent" object as this object's ID.
>>> r = Restaurant(place=p1, serves_hot_dogs=True, serves_pizza=False)
>>> r.save()

# A Restaurant can access its place.
>>> r.place
Demon Dogs the place

# A Place can access its restaurant, if available.
>>> p1.restaurant
Demon Dogs the restaurant

# p2 doesn't have an associated restaurant.
>>> p2.restaurant
Traceback (most recent call last):
    ...
DoesNotExist: Restaurant does not exist for {'place__id__exact': ...}

# Restaurant.objects.get_list() just returns the Restaurants, not the Places.
>>> list(Restaurant.objects)
[Demon Dogs the restaurant]

# Place.objects.get_list() returns all Places, regardless of whether they have
# Restaurants.
>>> list(Place.objects.filter(order_by=['name']))
[Ace Hardware the place, Demon Dogs the place]

>>> Restaurant.objects.get(place__id__exact=1)
Demon Dogs the restaurant
>>> Restaurant.objects.get(pk=1)
Demon Dogs the restaurant
>>> Restaurant.objects.get(place__exact=1)
Demon Dogs the restaurant
>>> Restaurant.objects.get(place__pk=1)
Demon Dogs the restaurant
>>> Restaurant.objects.get(place__name__startswith="Demon")
Demon Dogs the restaurant

>>> Place.objects.get(id__exact=1)
Demon Dogs the place
>>> Place.objects.get(pk=1)
Demon Dogs the place
>>> Place.objects.get(restaurant__place__exact=1)
Demon Dogs the place
>>> Place.objects.get(restaurant__pk=1)
Demon Dogs the place

# Add a Waiter to the Restaurant.
>>> w = r.waiter_set.add(name='Joe')
>>> w.save()
>>> w
Joe the waiter at Demon Dogs the restaurant

# Query the waiters
>>> list(Waiter.objects.filter(restaurant__place__exact=1))
[Joe the waiter at Demon Dogs the restaurant]
>>> list(Waiter.objects.filter(restaurant__pk=1))
[Joe the waiter at Demon Dogs the restaurant]
>>> list(Waiter.objects.filter(id__exact=1))
[Joe the waiter at Demon Dogs the restaurant]
>>> list(Waiter.objects.filter(pk=1))
[Joe the waiter at Demon Dogs the restaurant]

# Delete the restaurant; the waiter should also be removed
>>> r = Restaurant.objects.get(pk=1)
>>> r.delete()
"""
