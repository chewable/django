import unittest
from django.contrib.gis.gdal import SpatialReference, CoordTransform, OGRException, SRSException

class TestSRS:
    def __init__(self, wkt, **kwargs):
        self.wkt = wkt
        for key, value in kwargs.items():
            setattr(self, key, value)

# Some Spatial Reference examples
srlist = (TestSRS('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],TOWGS84[0,0,0,0,0,0,0],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]',
                  proj='+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs ',
                  epsg=4326, projected=False, geographic=True, local=False,
                  lin_name='unknown', ang_name='degree', lin_units=1.0, ang_units=0.0174532925199,
                  auth={'GEOGCS' : ('EPSG', '4326'), 'spheroid' : ('EPSG', '7030')},
                  attr=(('DATUM', 'WGS_1984'), (('SPHEROID', 1), '6378137'),('primem|authority', 'EPSG'),),
                  ),
          TestSRS('PROJCS["NAD83 / Texas South Central",GEOGCS["NAD83",DATUM["North_American_Datum_1983",SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","6269"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4269"]],PROJECTION["Lambert_Conformal_Conic_2SP"],PARAMETER["standard_parallel_1",30.28333333333333],PARAMETER["standard_parallel_2",28.38333333333333],PARAMETER["latitude_of_origin",27.83333333333333],PARAMETER["central_meridian",-99],PARAMETER["false_easting",600000],PARAMETER["false_northing",4000000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","32140"]]',
                  proj='+proj=lcc +lat_1=30.28333333333333 +lat_2=28.38333333333333 +lat_0=27.83333333333333 +lon_0=-99 +x_0=600000 +y_0=4000000 +ellps=GRS80 +datum=NAD83 +units=m +no_defs ',
                  epsg=32140, projected=True, geographic=False, local=False,
                  lin_name='metre', ang_name='degree', lin_units=1.0, ang_units=0.0174532925199,
                  auth={'PROJCS' : ('EPSG', '32140'), 'spheroid' : ('EPSG', '7019'), 'unit' : ('EPSG', '9001'),},
                  attr=(('DATUM', 'North_American_Datum_1983'),(('SPHEROID', 2), '298.257222101'),('PROJECTION','Lambert_Conformal_Conic_2SP'),),
                  ),
          TestSRS('PROJCS["NAD_1983_StatePlane_Texas_South_Central_FIPS_4204_Feet",GEOGCS["GCS_North_American_1983",DATUM["North_American_Datum_1983",SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["Lambert_Conformal_Conic_2SP"],PARAMETER["False_Easting",1968500.0],PARAMETER["False_Northing",13123333.33333333],PARAMETER["Central_Meridian",-99.0],PARAMETER["Standard_Parallel_1",28.38333333333333],PARAMETER["Standard_Parallel_2",30.28333333333334],PARAMETER["Latitude_Of_Origin",27.83333333333333],UNIT["Foot_US",0.3048006096012192]]',
                  proj='+proj=lcc +lat_1=28.38333333333333 +lat_2=30.28333333333334 +lat_0=27.83333333333333 +lon_0=-99 +x_0=600000 +y_0=3999999.999999999 +ellps=GRS80 +datum=NAD83 +to_meter=0.3048006096012192 +no_defs ',
                  epsg=None, projected=True, geographic=False, local=False,
                  lin_name='Foot_US', ang_name='Degree', lin_units=0.3048006096012192, ang_units=0.0174532925199,
                  auth={'PROJCS' : (None, None),},
                  attr=(('PROJCS|GeOgCs|spheroid', 'GRS_1980'),(('projcs', 9), 'UNIT'), (('projcs', 11), None),),
                  ),
          # This is really ESRI format, not WKT -- but the import should work the same
          TestSRS('LOCAL_CS["Non-Earth (Meter)",LOCAL_DATUM["Local Datum",0],UNIT["Meter",1.0],AXIS["X",EAST],AXIS["Y",NORTH]]',
                  esri=True, proj=None, epsg=None, projected=False, geographic=False, local=True,
                  lin_name='Meter', ang_name='degree', lin_units=1.0, ang_units=0.0174532925199,
                  attr=(('LOCAL_DATUM', 'Local Datum'), ('unit', 'Meter')),
                  ),
          )

# Well-Known Names
well_known = (TestSRS('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],TOWGS84[0,0,0,0,0,0,0],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]', wk='WGS84'),
              TestSRS('GEOGCS["WGS 72",DATUM["WGS_1972",SPHEROID["WGS 72",6378135,298.26,AUTHORITY["EPSG","7043"]],AUTHORITY["EPSG","6322"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4322"]]', wk='WGS72'),
              TestSRS('GEOGCS["NAD27",DATUM["North_American_Datum_1927",SPHEROID["Clarke 1866",6378206.4,294.9786982138982,AUTHORITY["EPSG","7008"]],AUTHORITY["EPSG","6267"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4267"]]', wk='NAD27'),
              TestSRS('GEOGCS["NAD83",DATUM["North_American_Datum_1983",SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","6269"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4269"]]', wk='NAD83'),
              TestSRS('PROJCS["NZGD49 / Karamea Circuit",GEOGCS["NZGD49",DATUM["New_Zealand_Geodetic_Datum_1949",SPHEROID["International 1924",6378388,297,AUTHORITY["EPSG","7022"]],TOWGS84[59.47,-5.04,187.44,0.47,-0.1,1.024,-4.5993],AUTHORITY["EPSG","6272"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4272"]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",-41.28991152777778],PARAMETER["central_meridian",172.1090281944444],PARAMETER["scale_factor",1],PARAMETER["false_easting",300000],PARAMETER["false_northing",700000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","27216"]]', wk='EPSG:27216'),
              )

bad_srlist = ('Foobar', 'OOJCS["NAD83 / Texas South Central",GEOGCS["NAD83",DATUM["North_American_Datum_1983",SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","6269"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4269"]],PROJECTION["Lambert_Conformal_Conic_2SP"],PARAMETER["standard_parallel_1",30.28333333333333],PARAMETER["standard_parallel_2",28.38333333333333],PARAMETER["latitude_of_origin",27.83333333333333],PARAMETER["central_meridian",-99],PARAMETER["false_easting",600000],PARAMETER["false_northing",4000000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","32140"]]',)

class SpatialRefTest(unittest.TestCase):

    def test01_wkt(self):
        "Testing initialization on valid OGC WKT."
        for s in srlist:
            srs = SpatialReference(s.wkt)

    def test02_bad_wkt(self):
        "Testing initialization on invalid WKT."
        for bad in bad_srlist:
            try:
                srs = SpatialReference(bad)
                srs.validate()
            except (SRSException, OGRException):
                pass
            else:
                self.fail('Should not have initialized on bad WKT "%s"!')

    def test03_get_wkt(self):
        "Testing getting the WKT."
        for s in srlist:
            srs = SpatialReference(s.wkt)
            self.assertEqual(s.wkt, srs.wkt)

    def test04_proj(self):
        "Test PROJ.4 import and export."

        for s in srlist:
            if s.proj:
                srs1 = SpatialReference(s.wkt)
                srs2 = SpatialReference(s.proj, 'proj')
                self.assertEqual(srs1.proj, srs2.proj)

    def test05_epsg(self):
        "Test EPSG import."
        for s in srlist:
            if s.epsg:
                srs1 = SpatialReference(s.wkt)
                srs2 = SpatialReference(s.epsg, 'epsg')
                self.assertEqual(srs1.wkt, srs2.wkt)

    def test07_boolean_props(self):
        "Testing the boolean properties."
        for s in srlist:
            srs = SpatialReference(s.wkt)
            self.assertEqual(s.projected, srs.projected)
            self.assertEqual(s.geographic, srs.geographic)

    def test08_angular_linear(self):
        "Testing the linear and angular units routines."
        for s in srlist:
            srs = SpatialReference(s.wkt)
            self.assertEqual(s.ang_name, srs.angular_name)
            self.assertEqual(s.lin_name, srs.linear_name)
            self.assertAlmostEqual(s.ang_units, srs.angular_units, 9)
            self.assertAlmostEqual(s.lin_units, srs.linear_units, 9)

    def test09_authority(self):
        "Testing the authority name & code routines."
        for s in srlist:
            if hasattr(s, 'auth'):
                srs = SpatialReference(s.wkt)
                for target, tup in s.auth.items():
                    self.assertEqual(tup[0], srs.auth_name(target))
                    self.assertEqual(tup[1], srs.auth_code(target))

    def test10_attributes(self):
        "Testing the attribute retrieval routines."
        for s in srlist:
            srs = SpatialReference(s.wkt)
            for tup in s.attr:
                att = tup[0] # Attribute to test
                exp = tup[1] # Expected result
                self.assertEqual(exp, srs[att])

    def test11_wellknown(self):
        "Testing Well Known Names of Spatial References."
        for s in well_known:
            srs = SpatialReference(s.wk)
            self.assertEqual(s.wkt, srs.wkt)

    def test12_coordtransform(self):
        "Testing initialization of a CoordTransform."
        target = SpatialReference('WGS84')
        for s in srlist:
            if s.proj:
                ct = CoordTransform(SpatialReference(s.wkt), target)
    
def suite():
    s = unittest.TestSuite()
    s.addTest(unittest.makeSuite(SpatialRefTest))
    return s

def run(verbosity=2):
    unittest.TextTestRunner(verbosity=verbosity).run(suite())
