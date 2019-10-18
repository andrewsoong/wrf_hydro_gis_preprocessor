# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# Copyright UCAR (c) 2019
# University Corporation for Atmospheric Research(UCAR)
# National Center for Atmospheric Research(NCAR)
# Research Applications Laboratory(RAL)
# P.O.Box 3000, Boulder, Colorado, 80307-3000, USA
# 24/09/2019
#
# Name:        module1
# Purpose:
# Author:      $ Kevin Sampson
# Created:     24/09/2019
# Licence:     <your licence>
# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=

# --- Import Modules --- #

# Import Python core modules
import sys
sys.dont_write_bytecode = True
import time
import os
import glob
import csv
import zipfile
from zipfile import ZipFile, ZipInfo
from collections import defaultdict                                             # Added 09/03/2015Needed for topological sorting algorthm
from itertools import takewhile, count                                          # Added 09/03/2015Needed for topological sorting algorthm

# Change any environment variables here
#os.environ["OGR_WKT_PRECISION"] = "5"                                           # Change the precision of coordinates

# Import Additional Modules
import ogr
import osr
import gdal
import gdalconst
from gdalnumeric import *                                                       # Assists in using BandWriteArray, BandReadAsArray, and CopyDatasetInfo
from osgeo import gdal_array
import netCDF4
import numpy
import subprocess                                                               # Used for calling gdal command line functions
#from subprocess import Popen, PIPE

# Import whitebox.
#from whitebox import whitebox_tools                                             # Required if first-time import
from whitebox.WBT.whitebox_tools import WhiteboxTools

# Module options
gdal.UseExceptions()                                                            # this allows GDAL to throw Python Exceptions
gdal.PushErrorHandler('CPLQuietErrorHandler')

# Add Proj directory to path
conda_env_path = os.path.join(os.path.dirname(sys.executable))
internal_datadir = os.path.join(conda_env_path, "Library", "share", "proj")
os.environ["PROJ_LIB"] = internal_datadir

### Pyproj
##import pyproj
##pyproj.datadir.set_data_dir = internal_datadir

# --- End Import Modules --- #

# --- Global Variables --- #

# Global attributes for altering the sphere radius used in computations. Do not alter sphere_radius for standard WRF-Hydro simulations
sphere_radius = 6370000.0                                                       # Radius of sphere to use (WRF Default = 6370000.0m)

#Other Globals
RasterDriver = 'GTiff'
VectorDriver = 'ESRI Shapefile'                                                # Output vector file format (OGR driver name)

# Initiate dictionaries of GEOGRID projections and parameters
#   See http://www.mmm.ucar.edu/wrf/users/docs/user_guide_V3/users_guide_chap3.htm#_Description_of_the_1
projdict = {1: 'Lambert Conformal Conic',
            2: 'Polar Stereographic',
            3: 'Mercator',
            6: 'Cylindrical Equidistant'}
CF_projdict = {1: "lambert_conformal_conic",
                2: "polar_stereographic",
                3: "mercator",
                6: "latitude_longitude",
                0: "crs"}

# Output file types
outNCType = 'NETCDF4_CLASSIC'                                                   # Define the output netCDF version for RouteLink.nc and LAKEPARM.nc

# Default output file names
FullDom = 'Fulldom_hires.nc'                                                    # Default Full Domain routing grid nc file
LDASFile = 'GEOGRID_LDASOUT_Spatial_Metadata.nc'                                # Defualt LDASOUT domain grid nc file
LK_nc = 'LAKEPARM.nc'                                                           # Default Lake parameter table name [.nc]
LK_tbl = 'LAKEPARM.TBL'                                                         # Default Lake parameter table name [.TBL]
RT_nc = 'Route_Link.nc'                                                         # Default Route Link parameter table name
GW_nc = 'GWBUCKPARM.nc'                                                         # Default groundwater bucket parameter table name
GWGRID_nc = 'GWBASINS.nc'
GW_ASCII = 'gw_basns_geogrid.txt'                                               # Default Groundwater Basins ASCII grid output
GW_TBL = 'GWBUCKPARM.TBL'
StreamSHP = 'streams.shp'                                                       # Default streams shapefile name

PpVersion = 'v5.2 (09/2019)'                                                    # WRF-Hydro ArcGIS Pre-processor version to add to FullDom metadata
CFConv = 'CF-1.5'                                                               # CF-Conventions version to place in the 'Conventions' attribute of RouteLink files

# Other Global Variables
NoDataVal = -9999                                                               # Default NoData value for gridded variables
walker = 3                                                                      # Number of cells to walk downstream before gaged catchment delineation
LK_walker = 3                                                                   # Number of cells to walk downstream to get minimum lake elevation
z_limit = 1000.0                                                                # Maximum fill depth (z-limit) between a sink and it's pour point
lksatfac_val = 1000.0                                                           # Default LKSATFAC value (unitless coefficient)
minDepth = 1.0                                                                  # Minimum active lake depth for lakes with no elevation variation

# Channel Routing default parameters
Qi = 0                                                                          # Initial Flow in link (cms)
MusK = 3600                                                                     # Muskingum routing time (s)
MusX = 0.2                                                                      # Muskingum weighting coefficient
n = 0.035                                                                       # Manning's roughness
ChSlp = 0.05                                                                    # Channel Side Slope (%; drop/length)
BtmWdth = 5                                                                     # Bottom Width of Channel (m)
Kc = 0                                                                          # channel conductivity (mm/hour)

#Default Lake Routing parameters
OrificeC = 0.1
OrificA = 1.0
WeirC = 0.4
WeirL = 10.0                                                                    # New default prescribed by D. Yates 5/11/2017 (10m default weir length). Old default weir length (0.0m).
ifd_Val = 0.90                                                                  # Default initial fraction water depth (90%)
out_LKtype = ['nc']                                                             # Default output lake parameter file format ['nc', 'ascii']

# Default groundwater bucket (GWBUCKPARM) parameters
coeff = 1.0000                                                                  # Bucket model coefficient
expon = 3.000                                                                   # Bucket model exponent
zmax = 50.00                                                                    # Conceptual maximum depth of the bucket
zinit = 10.0000                                                                 # Initial depth of water in the bucket model

# Unify all coordinate system variables to have the same name ("crs"). Ths makes it easier for WRF-Hydro output routines to identify the variable and transpose it to output files
crsVarname = True                                                               # Switch to make all coordinate system variables = "crs" instead of related to the coordinate system name
crsVar = CF_projdict[0]                                                         # Expose this as a global for other functions in other scripts to use
wgs84_proj4 = '+proj=longlat +datum=WGS84 +no_defs'

# Point time-series CF-netCDF file coordinate system
'''Note that the point netCDF files are handled using a separate coordinate system than the grids.
This is because input data are usually in WGS84 or some other global spheroidal datum. We treat
these coordinates as though there is no difference between a sphere and a spheroid with respect
to latitude. Thus, we can choose an output coordinate system for the points, although no
transformation is performed. Properly transforming the points back and forth betwen sphere and
spheroid dramatically increases the runtime of the tools, with clear obvious benefit.'''
pointCF = True                                                                  # Switch to turn on CF-netCDF point time-series metadata attributes
pointSR = 4326                                                                  # The spatial reference system of the point time-series netCDF files (RouteLink, LAKEPARM). NAD83=4269, WGS84=4326

# Global attributes for altering the sphere radius used in computations. Do not alter sphere_radius for standard WRF-Hydro simulations
sphere_radius = 6370000.0                                                       # Radius of sphere to use (WRF Default = 6370000.0m)
wkt_text = "GEOGCS['GCS_Sphere_CUSTOM',DATUM['D_Sphere',SPHEROID['Sphere',%s,0.0]],PRIMEM['Greenwich',0.0],UNIT['Degree',0.0174532925199433]];-400 -400 1000000000;-100000 10000;-100000 10000;8.99462786704589E-09;0.001;0.001;IsHighPrecision" %sphere_radius

# Temporary output file names for Whitebox outputs
dir_d8 = "dir_d8.tif"
fill_pits = "fill_pits.tif"
streams = "streams.tif"
strahler = "strahler.tif"
sub_basins = "sub_basins.tif"
snapPour1 = 'snapped_pour_points_1.shp'                                     # Pour points snapped to nearest grid cell center
snapPour2 = 'snapped_pour_points_2.shp'                                     # Pour points snapped with higher tolerance
watersheds = "watersheds.tif"                                               # Watersheds delineated above pour points

# --- End Global Variables --- #

# --- Classes --- #
class ZipCompat(ZipFile):
    def __init__(self, *args, **kwargs):
        ZipFile.__init__(self, *args, **kwargs)

    def extract(self, member, path=None):
        if not isinstance(member, ZipInfo):
            member = self.getinfo(member)
        if path is None:
            path = os.getcwd()
        return self._extract_member(member, path)

    def extractall(self, path=None, members=None, pwd=None):
        if members is None:
            members = self.namelist()
        for zipinfo in members:
            self.extract(zipinfo, path)

    def _extract_member(self, member, targetpath):
        if (targetpath[-1:] in (os.path.sep, os.path.altsep)
            and len(os.path.splitdrive(targetpath)[1]) > 1):
            targetpath = targetpath[:-1]
        if member.filename[0] == '/':
            targetpath = os.path.join(targetpath, member.filename[1:])
        else:
            targetpath = os.path.join(targetpath, member.filename)
        targetpath = os.path.normpath(targetpath)
        upperdirs = os.path.dirname(targetpath)
        if upperdirs and not os.path.exists(upperdirs):
            os.makedirs(upperdirs)
        if member.filename[-1] == '/':
            if not os.path.isdir(targetpath):
                os.mkdir(targetpath)
            return targetpath
        #target = file(targetpath, "wb")
        target = open(targetpath, "wb")                                         # 5/31/2019: Supporting Python3
        try:
            target.write(self.read(member.filename))
        finally:
            target.close()
        return targetpath

class WRF_Hydro_Grid():
    '''
    Class with which to create the WRF-Hydro grid representation. Provide grid
    information to initiate the class, and use getgrid() to generate a grid mesh
    and index information about the intersecting cells.

    Note:  The i,j index begins with (1,1) in the upper-left corner.
    '''
    def __init__(self, rootgrp):

        '''                                                                                  .
        9/24/2019:
            This function will create a georeferenced raster object as well as projection
            definition from an input WPS GEOGRID (geo_em.d0*.nc).

            See the WPS Documentation for more information:

            http://www2.mmm.ucar.edu/wrf/users/docs/user_guide_V3/users_guide_chap3.htm

        '''
        tic1 = time.time()
        # First step: Import and georeference NetCDF file
        print('Step 1: WPS netCDF projection identification initiated...')

        corner_index = 13                                                           # 13 = Upper left of the Unstaggered grid

        # Loop through global variables in NetCDF file to gather projection information
        dimensions = rootgrp.dimensions
        globalAtts = rootgrp.__dict__                                               # Read all global attributes into a dictionary
        self.map_pro = globalAtts['MAP_PROJ']                                            # Find out which projection this GEOGRID file is in
        print('    Map Projection: {0}'.format(projdict[self.map_pro]))

        # Collect grid corner XY and DX DY for creating ascii raster later
        if 'corner_lats' in globalAtts:
            corner_lat = globalAtts['corner_lats'][corner_index].astype(numpy.float64)
        if 'corner_lons' in globalAtts:
            corner_lon = globalAtts['corner_lons'][corner_index].astype(numpy.float64)
        if 'DX' in globalAtts:
            self.DX = globalAtts['DX'].astype(numpy.float32)
        if 'DY' in globalAtts:
            self.DY = -globalAtts['DY'].astype(numpy.float32)

        # Collect necessary information to put together the projection file
        if 'TRUELAT1' in globalAtts:
            standard_parallel_1 = globalAtts['TRUELAT1'].astype(numpy.float64)
        if 'TRUELAT2' in globalAtts:
            standard_parallel_2 = globalAtts['TRUELAT2'].astype(numpy.float64)
        if 'STAND_LON' in globalAtts:
            central_meridian = globalAtts['STAND_LON'].astype(numpy.float64)
        if 'POLE_LAT' in globalAtts:
            pole_latitude = globalAtts['POLE_LAT'].astype(numpy.float64)
        if 'POLE_LON' in globalAtts:
            pole_longitude = globalAtts['POLE_LON'].astype(numpy.float64)
        if 'MOAD_CEN_LAT' in globalAtts:
            print('    Using MOAD_CEN_LAT for latitude of origin.')
            latitude_of_origin = globalAtts['MOAD_CEN_LAT'].astype(numpy.float64)
        elif 'CEN_LAT' in globalAtts:
            print('    Using CEN_LAT for latitude of origin.')
            latitude_of_origin = globalAtts['CEN_LAT'].astype(numpy.float64)
        del globalAtts

        self.nrows = len(dimensions['south_north'])
        self.ncols = len(dimensions['west_east'])
        del dimensions

        # Initiate OSR spatial reference object - See http://gdal.org/java/org/gdal/osr/SpatialReference.html
        proj = osr.SpatialReference()

        if self.map_pro == 1:
            # Lambert Conformal Conic
            if 'standard_parallel_2' in locals():
                print('    Using Standard Parallel 2 in Lambert Conformal Conic map projection.')
                proj.SetLCC(standard_parallel_1, standard_parallel_2, latitude_of_origin, central_meridian, 0, 0)
                #proj.SetLCC(double stdp1, double stdp2, double clat, double clong, double fe, double fn)        # fe = False Easting, fn = False Northing
            else:
                proj.SetLCC1SP(latitude_of_origin, central_meridian, 1, 0, 0)       # Scale = 1???
                #proj.SetLCC1SP(double clat, double clong, double scale, double fe, double fn)       # 1 standard parallell

        elif self.map_pro == 2:
            # Polar Stereographic
            phi1 = standard_parallel_1

            ### Back out the central_scale_factor (minimum scale factor?) using formula below using Snyder 1987 p.157 (USGS Paper 1395)
            ##phi = math.copysign(float(pole_latitude), float(latitude_of_origin))    # Get the sign right for the pole using sign of CEN_LAT (latitude_of_origin)
            ##central_scale_factor = (1 + (math.sin(math.radians(phi1))*math.sin(math.radians(phi))) + (math.cos(math.radians(float(phi1)))*math.cos(math.radians(phi))))/2

            # Method where central scale factor is k0, Derivation from C. Rollins 2011, equation 1: http://earth-info.nga.mil/GandG/coordsys/polar_stereographic/Polar_Stereo_phi1_from_k0_memo.pdf
            # Using Rollins 2011 to perform central scale factor calculations. For a sphere, the equation collapses to be much  more compact (e=0, k90=1)
            central_scale_factor = (1 + math.sin(math.radians(abs(phi1))))/2        # Equation for k0, assumes k90 = 1, e=0. This is a sphere, so no flattening
            print('        Central Scale Factor: {0}'.format(central_scale_factor))

            #proj1.SetPS(latitude_of_origin, central_meridian, central_scale_factor, 0, 0)    # example: proj1.SetPS(90, -1.5, 1, 0, 0)
            proj.SetPS(pole_latitude, central_meridian, central_scale_factor, 0, 0)    # Adjusted 8/7/2017 based on changes made 4/4/2017 as a result of Monaghan's polar sterographic domain. Example: proj1.SetPS(90, -1.5, 1, 0, 0)
            #proj.SetPS(double clat, double clong, double scale, double fe, double fn)

        elif self.map_pro == 3:
            # Mercator Projection
            proj.SetMercator(latitude_of_origin, central_meridian, 1, 0, 0)     # Scale = 1???
            #proj.SetMercator(double clat, double clong, double scale, double fe, double fn)

        elif self.map_pro == 6:
            # Cylindrical Equidistant (or Rotated Pole)
            if pole_latitude != float(90) or pole_longitude != float(0):
                # if pole_latitude, pole_longitude, or stand_lon are changed from thier default values, the pole is 'rotated'.
                print('[PROBLEM!] Cylindrical Equidistant projection with a rotated pole is not currently supported.')
                raise SystemExit
            else:
                proj.SetEquirectangular(latitude_of_origin, central_meridian, 0, 0)
                #proj.SetEquirectangular(double clat, double clong, double fe, double fn)
                #proj.SetEquirectangular2(double clat, double clong, double pseudostdparallellat, double fe, double fn)

        # Set Geographic Coordinate system (datum) for projection
        proj.SetGeogCS('WRF_Sphere', 'Sphere', '', sphere_radius, 0.0)              # Could try 104128 (EMEP Sphere) well-known?
        #proj.SetGeogCS(String pszGeogName, String pszDatumName, String pszSpheroidName, double dfSemiMajor, double dfInvFlattening)

        # Set the origin for the output raster (in GDAL, usuall upper left corner) using projected corner coordinates
        wgs84_proj = osr.SpatialReference()
        wgs84_proj.ImportFromProj4(wgs84_proj4)
        transform = osr.CoordinateTransformation(wgs84_proj, proj)
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint_2D(corner_lon, corner_lat)
        point.Transform(transform)
        self.x00 = point.GetX(0)
        self.y00 = point.GetY(0)
        self.proj = proj
        self.WKT = proj.ExportToWkt()
        self.proj4 = proj.ExportToProj4()
        del point, transform, wgs84_proj
        print('    Step 1 completed without error in {0: 3.2f} seconds.'.format(time.time()-tic1))

    def regrid(self, regrid_factor):
        '''
        Change the grid cell spacing while keeping all other grid parameters
        the same.
        '''
        self.DX = float(self.DX)/float(regrid_factor)
        self.DY = float(self.DY)/float(regrid_factor)
        self.nrows = int(self.nrows*regrid_factor)
        self.ncols = int(self.ncols*regrid_factor)
        print('  New grid spacing: dx={0}, dy={1}'.format(self.DX, self.DY))
        print('  New dimensions: rows={0}, cols={1}'.format(self.nrows, self.ncols))
        return self

    def GeoTransform(self):
        '''
        Return the affine transformation for this grid. Assumes a 0 rotation grid.
        (top left x, w-e resolution, 0=North up, top left y, 0 = North up, n-s pixel resolution (negative value))
        '''
        return (self.x00, self.DX, 0, self.y00, 0, self.DY)

    def GeoTransformStr(self):
        return ' '.join([str(item) for item in self.GeoTransform()])

    def getxy(self):
        """
        This function will use the affine transformation (GeoTransform) to produce an
        array of X and Y 1D arrays. Note that the GDAL affine transformation provides
        the grid cell coordinates from the upper left corner. This is typical in GIS
        applications. However, WRF uses a south_north ordering, where the arrays are
        written from the bottom to the top.

        The input raster object will be used as a template for the output rasters.
        """
        print('    Starting Process: Building to XMap/YMap')

        # Build i,j arrays
        j = numpy.arange(self.nrows) + float(0.5)                              # Add 0.5 to estimate coordinate of grid cell centers
        i = numpy.arange(self.ncols) + float(0.5)                               # Add 0.5 to estimate coordinate of grid cell centers

        # col, row to x, y   From https://www.perrygeo.com/python-affine-transforms.html
        x = (i * self.DX) + self.x00
        y = (j * self.DY) + self.y00
        del i, j

        # Create 2D arrays from 1D
        xmap = numpy.repeat(x[numpy.newaxis, :], y.shape, 0)
        ymap = numpy.repeat(y[:, numpy.newaxis], x.shape, 1)
        del x, y
        print('    Conversion of input raster to XMap/YMap completed without error.')
        return xmap, ymap

    def grid_extent(self):
        '''
        Return the grid bounding extent [xMin, yMin, xMax, yMax]
        '''
        xMax = self.x00 + (float(self.ncols)*self.DX)
        yMin = self.y00 + (float(self.nrows)*self.DY)
        return [self.x00, yMin, xMax, self.y00]

    def numpy_to_Raster(self, in_arr, quiet=True):
        '''This funciton takes in an input netCDF file, a variable name, the ouput
        raster name, and the projection definition and writes the grid to the output
        raster. This is useful, for example, if you have a FullDom netCDF file and
        the GEOGRID that defines the domain. You can output any of the FullDom variables
        to raster.'''
        try:
            # Set up driver for GeoTiff output
            driver = gdal.GetDriverByName('Mem')                                # Write to Memory
            if driver is None:
                print('    {0} driver not available.'.format('Memory'))
            gdaltype = gdal_array.NumericTypeCodeToGDALTypeCode(in_arr.dtype)
            DataSet = driver.Create('', in_arr.shape[1], in_arr.shape[0], 1, gdaltype) # the '1' is for band 1.
            if proj_in:
                DataSet.SetProjection(self.WKT)
            DataSet.SetGeoTransform(self.GeoTransform(self))
            DataSet.GetRasterBand(1).WriteArray(in_arr)                         # Write the array
            #BandWriteArray(DataSet.GetRasterBand(1), in_arr)
            stats = DataSet.GetRasterBand(1).GetStatistics(0,1)                 # Calculate statistics
            #stats = DataSet.GetRasterBand(1).ComputeStatistics(0)              # Force recomputation of statistics
            driver = None
        except RuntimeError:
            print('ERROR: Unable to build output raster from numpy array.')
            raise SystemExit
        return DataSet

    def boundarySHP(self, outputFile, DriverName='ESRI Shapefile'):
        '''Build a single-feature rectangular polygon that represents the boundary
        of the WRF/WRF-Hydro domain. '''

        # Now convert it to a vector file with OGR
        tic1 = time.time()
        drv = ogr.GetDriverByName(DriverName)
        if drv is None:
            print('      %s driver not available.' % DriverName)
        else:
            print('      %s driver is available.' % DriverName)
            datasource = drv.CreateDataSource(outputFile)
        if datasource is None:
            print('      Creation of output file failed.\n')
            raise SystemExit

        # Create output polygon vector file
        proj_in = self.proj
        layer = datasource.CreateLayer('boundary', geom_type=ogr.wkbPolygon)
        if layer is None:
            print('        Layer creation failed.\n')
            raise SystemExit
        LayerDef = layer.GetLayerDefn()                                             # Fetch the schema information for this layer

        # Create polygon object that is fully inside the outer edge of the domain
        [xMin, yMin, xMax, yMax] = self.grid_extent()
        ring = ogr.Geometry(type=ogr.wkbLinearRing)
        ring.AddPoint(xMin, yMax)
        ring.AddPoint(xMax, yMax)
        ring.AddPoint(xMax, yMin)
        ring.AddPoint(xMin, yMin)
        ring.AddPoint(xMin, yMax)                                     #close ring
        geometry = ogr.Geometry(type=ogr.wkbPolygon)
        geometry.AssignSpatialReference(proj_in)
        geometry.AddGeometry(ring)

        # Create the feature
        feature = ogr.Feature(LayerDef)                                     # Create a new feature (attribute and geometry)
        feature.SetGeometry(geometry)                                      # Make a feature from geometry object
        layer.CreateFeature(feature)
        print('Done producing output vector polygon shapefile in {0: 3.2f} seconds'.format(time.time()-tic1))
        datasource = myRing = feature = layer = None        # geometry
        return geometry

    def xy_to_grid_ij(self, x, y):
        '''
        This function converts a coordinate in (x,y) to the correct row and column
        on a grid. Code from: https://www.perrygeo.com/python-affine-transforms.html
        '''
        # x,y to col,row.
        col = int((x - self.x00) / self.DX)
        row = int((y - self.y00) / self.DY)
        return row, col

    def grid_ij_to_xy(self, col, row):
        '''
        This function converts a 2D grid index (i,j) the grid cell center coordinate
        (x,y) in the grid coordinate system.
        Code from: https://www.perrygeo.com/python-affine-transforms.html
        '''
        # col, row to x, y
        x = (col * self.DX) + self.x00 + self.DX/2.0
        y = (row * self.DY) + self.y00 + self.DY/2.0
        return x, y

    def project_to_model_grid(self, in_raster, saveRaster=False, OutGTiff=None, resampling=gdal.GRA_Bilinear):
        """
        The second step creates a high resolution topography raster using a hydrologically-
        corrected elevation dataset.

        grid object extent and coordinate system will be respected.
        """
        tic1 = time.time()
        print('    Raster resampling initiated...')

        te = self.grid_extent()                                         # Target Extent
        print('    The High-resolution dataset will be {0}m'.format(str(self.DX)))

        # Use Warp command
        OutRaster = gdal.Warp('', in_raster, format='MEM', xRes=self.DX, yRes=self.DY,
                            outputBounds=te, outputBoundsSRS=self.WKT,
                            resampleAlg=resampling, dstSRS=self.WKT,
                            errorThreshold=0.0)
        # Other options to gdal.Warp: dstSRS='EPSG:32610', dstNodata=1, srcNodata=1, outputType=gdal.GDT_Int16
        #   transformerOptions=[ 'SRC_METHOD=NO_GEOTRANSFORM', 'DST_METHOD=NO_GEOTRANSFORM']
        #   width=Xsize_out, height=Ysize_out, targetAlignedPixels=True
        del te

        # Save to disk
        if saveRaster:
            if OutRaster is not None:
                try:
                    target_ds = gdal.GetDriverByName(RasterDriver).CreateCopy(OutGTiff, OutRaster)
                    target_ds = None
                except:
                    pass
        # Finish
        print('    Projected input raster to routing grid in {0: 3.2f} seconds.'.format(time.time()-tic1))
        return OutRaster
#gridder_obj = Gridder_Layer(WKT, DX, DY, x00, y00, nrows, ncols)

# --- End Classes --- #

# --- Functions --- #

def zipws(zipfile, path, zip, keep, nclist):
    path = os.path.normpath(path)
    for dirpath, dirnames, filenames in os.walk(path):
        for file in filenames:
            if file in nclist:
                if keep:
                    try:
                        zip.write(os.path.join(dirpath, file), os.path.join(os.sep + os.path.join(dirpath, file)[len(path) + len(os.sep):]))
                    except:
                        print('Exception encountered while trying to write to output zip file.')

def zipUpFolder(folder, outZipFile, nclist):
    try:
        zip = zipfile.ZipFile(outZipFile, 'w', zipfile.ZIP_DEFLATED, allowZip64=True)
        zipws(zipfile, str(folder), zip, 'CONTENTS_ONLY', nclist)
        zip.close()
    except RuntimeError:
        print('Exception encountered while trying to write to output zip file.')
        pass

def flip_grid(array):
    '''This function takes a three dimensional array and flips it up-down to
    correct for the netCDF storage of these grids.'''
    array = array[::-1]                                                         # Flip 2D grid up-down
    return array

def numpy_to_Raster(in_arr, proj_in=None, DX=1, DY=-1, x00=0, y00=0, quiet=True):
    '''This funciton takes in an input netCDF file, a variable name, the ouput
    raster name, and the projection definition and writes the grid to the output
    raster. This is useful, for example, if you have a FullDom netCDF file and
    the GEOGRID that defines the domain. You can output any of the FullDom variables
    to raster.'''

    tic1 = time.time()
    try:
        # Set up driver for GeoTiff output
        driver = gdal.GetDriverByName('Mem')                                # Write to Memory
        if driver is None:
            print('    {0} driver not available.'.format('Memory'))

        # Set up the dataset and define projection/raster info
        gdaltype = gdal_array.NumericTypeCodeToGDALTypeCode(in_arr.dtype)
        DataSet = driver.Create('', in_arr.shape[1], in_arr.shape[0], 1, gdaltype) # the '1' is for band 1.
        if proj_in:
            DataSet.SetProjection(proj_in.ExportToWkt())
        DataSet.SetGeoTransform((x00, DX, 0, y00, 0, DY))                      # (top left x, w-e resolution, 0=North up, top left y, 0 = North up, n-s pixel resolution (negative value))
        #DataSet.GetRasterBand(1).WriteArray(in_arr)                             # Write the array
        BandWriteArray(DataSet.GetRasterBand(1), in_arr)
        stats = DataSet.GetRasterBand(1).GetStatistics(0,1)                     # Calculate statistics
        #stats = DataSet.GetRasterBand(1).ComputeStatistics(0)                  # Force recomputation of statistics
        driver = None

    except RuntimeError:
        print('ERROR: Unable to build output raster from numpy array.')
        raise SystemExit

    # Clear objects and return
    if not quiet:
        print('      Created raster in-memory from numpy array in {0:3.2f} seconds.'.format(time.time()-tic1))
    return DataSet

def georeference_geogrid_file(rootgrp):
    '''                                                                                  .
    9/24/2019:
        This function will create a georeferenced raster object as well as projection
        definition from an input WPS GEOGRID (geo_em.d0*.nc).

        See the WPS Documentation for more information:

        http://www2.mmm.ucar.edu/wrf/users/docs/user_guide_V3/users_guide_chap3.htm

    '''
    tic1 = time.time()

    # First step: Import and georeference NetCDF file
    print('Step 1: WPS netCDF projection identification initiated...')

    corner_index = 13                                                           # 13 = Upper left of the Unstaggered grid

    # Read input WPS GEOGRID file
    # Loop through global variables in NetCDF file to gather projection information
    globalAtts = rootgrp.__dict__                                               # Read all global attributes into a dictionary
    map_pro = globalAtts['MAP_PROJ']                                            # Find out which projection this GEOGRID file is in
    print('    Map Projection: {0}'.format(projdict[map_pro]))

    # Collect grid corner XY and DX DY for creating ascii raster later
    if 'corner_lats' in globalAtts:
        corner_lat = globalAtts['corner_lats'][corner_index].astype(numpy.float64)
    if 'corner_lons' in globalAtts:
        corner_lon = globalAtts['corner_lons'][corner_index].astype(numpy.float64)
    if 'DX' in globalAtts:
        DX = globalAtts['DX'].astype(numpy.float32)
    if 'DY' in globalAtts:
        DY = -globalAtts['DY'].astype(numpy.float32)

    # Collect necessary information to put together the projection file
    if 'TRUELAT1' in globalAtts:
        standard_parallel_1 = globalAtts['TRUELAT1'].astype(numpy.float64)
    if 'TRUELAT2' in globalAtts:
        standard_parallel_2 = globalAtts['TRUELAT2'].astype(numpy.float64)
    if 'STAND_LON' in globalAtts:
        central_meridian = globalAtts['STAND_LON'].astype(numpy.float64)
    if 'POLE_LAT' in globalAtts:
        pole_latitude = globalAtts['POLE_LAT'].astype(numpy.float64)
    if 'POLE_LON' in globalAtts:
        pole_longitude = globalAtts['POLE_LON'].astype(numpy.float64)
    if 'MOAD_CEN_LAT' in globalAtts:
        print('    Using MOAD_CEN_LAT for latitude of origin.')
        latitude_of_origin = globalAtts['MOAD_CEN_LAT'].astype(numpy.float64)         # Added 2/26/2017 by KMS
    elif 'CEN_LAT' in globalAtts:
        print('    Using CEN_LAT for latitude of origin.')
        latitude_of_origin = globalAtts['CEN_LAT'].astype(numpy.float64)
    del globalAtts

    # Initiate OSR spatial reference object - See http://gdal.org/java/org/gdal/osr/SpatialReference.html
    proj = osr.SpatialReference()

    if map_pro == 1:
        # Lambert Conformal Conic
        if 'standard_parallel_2' in locals():
            print('    Using Standard Parallel 2 in Lambert Conformal Conic map projection.')
            proj.SetLCC(standard_parallel_1, standard_parallel_2, latitude_of_origin, central_meridian, 0, 0)
            #proj.SetLCC(double stdp1, double stdp2, double clat, double clong, double fe, double fn)        # fe = False Easting, fn = False Northing
        else:
            proj.SetLCC1SP(latitude_of_origin, central_meridian, 1, 0, 0)       # Scale = 1???
            #proj.SetLCC1SP(double clat, double clong, double scale, double fe, double fn)       # 1 standard parallell

    elif map_pro == 2:
        # Polar Stereographic
        phi1 = standard_parallel_1

        ### Back out the central_scale_factor (minimum scale factor?) using formula below using Snyder 1987 p.157 (USGS Paper 1395)
        ##phi = math.copysign(float(pole_latitude), float(latitude_of_origin))    # Get the sign right for the pole using sign of CEN_LAT (latitude_of_origin)
        ##central_scale_factor = (1 + (math.sin(math.radians(phi1))*math.sin(math.radians(phi))) + (math.cos(math.radians(float(phi1)))*math.cos(math.radians(phi))))/2

        # Method where central scale factor is k0, Derivation from C. Rollins 2011, equation 1: http://earth-info.nga.mil/GandG/coordsys/polar_stereographic/Polar_Stereo_phi1_from_k0_memo.pdf
        # Using Rollins 2011 to perform central scale factor calculations. For a sphere, the equation collapses to be much  more compact (e=0, k90=1)
        central_scale_factor = (1 + math.sin(math.radians(abs(phi1))))/2        # Equation for k0, assumes k90 = 1, e=0. This is a sphere, so no flattening
        print('        Central Scale Factor: {0}'.format(central_scale_factor))

        #proj1.SetPS(latitude_of_origin, central_meridian, central_scale_factor, 0, 0)    # example: proj1.SetPS(90, -1.5, 1, 0, 0)
        proj.SetPS(pole_latitude, central_meridian, central_scale_factor, 0, 0)    # Adjusted 8/7/2017 based on changes made 4/4/2017 as a result of Monaghan's polar sterographic domain. Example: proj1.SetPS(90, -1.5, 1, 0, 0)
        #proj.SetPS(double clat, double clong, double scale, double fe, double fn)

    elif map_pro == 3:
        # Mercator Projection
        proj.SetMercator(latitude_of_origin, central_meridian, 1, 0, 0)     # Scale = 1???
        #proj.SetMercator(double clat, double clong, double scale, double fe, double fn)

    elif map_pro == 6:
        # Cylindrical Equidistant (or Rotated Pole)
        if pole_latitude != float(90) or pole_longitude != float(0):
            # if pole_latitude, pole_longitude, or stand_lon are changed from thier default values, the pole is 'rotated'.
            print('[PROBLEM!] Cylindrical Equidistant projection with a rotated pole is not currently supported.')
            raise SystemExit
        else:
            proj.SetEquirectangular(latitude_of_origin, central_meridian, 0, 0)
            #proj.SetEquirectangular(double clat, double clong, double fe, double fn)
            #proj.SetEquirectangular2(double clat, double clong, double pseudostdparallellat, double fe, double fn)

    # Set Geographic Coordinate system (datum) for projection
    proj.SetGeogCS('WRF_Sphere', 'Sphere', '', sphere_radius, 0.0)              # Could try 104128 (EMEP Sphere) well-known?
    #proj.SetGeogCS(String pszGeogName, String pszDatumName, String pszSpheroidName, double dfSemiMajor, double dfInvFlattening)

    # Set the origin for the output raster (in GDAL, usuall upper left corner) using projected corner coordinates
    wgs84_proj = osr.SpatialReference()
    #wgs84_proj.ImportFromEPSG(4326)
    wgs84_proj.ImportFromProj4(wgs84_proj4)
    transform = osr.CoordinateTransformation(wgs84_proj, proj)
    point = ogr.Geometry(ogr.wkbPoint)
    point.AddPoint_2D(corner_lon, corner_lat)
    point.Transform(transform)
    x00 = point.GetX(0)
    y00 = point.GetY(0)
    del point, transform, wgs84_proj

    # Process: Define Projection
    print('    Step 1 completed without error in {0: 3.2f} seconds.'.format(time.time()-tic1))
    return proj, map_pro, DX, DY, x00, y00

def add_CRS_var(rootgrp, sr, map_pro, CoordSysVarName, grid_mapping, PE_string, GeoTransformStr=None):
    '''
    10/13/2017 (KMS):
        This function was added to generalize the creating of a CF-compliant
        coordinate reference system variable. This was modularized in order to
        create CRS variables for both gridded and point time-series CF-netCDF
        files.
    '''
    tic1 = time.time()

    # Scalar projection variable - http://www.unidata.ucar.edu/software/thredds/current/netcdf-java/reference/StandardCoordinateTransforms.html
    proj_var = rootgrp.createVariable(CoordSysVarName, 'S1')                    # (Scalar Char variable)
    proj_var.transform_name = grid_mapping                                      # grid_mapping. grid_mapping_name is an alias for this
    proj_var.grid_mapping_name = grid_mapping                                   # for CF compatibility
    proj_var.esri_pe_string = PE_string                                         # For ArcGIS. Not required if esri_pe_string exists in the 2D variable attributes
    #proj_var.spatial_ref = PE_string                                            # For GDAl
    proj_var.long_name = "CRS definition"                                       # Added 10/13/2017 by KMS to match GDAL format
    proj_var.longitude_of_prime_meridian = 0.0                                  # Added 10/13/2017 by KMS to match GDAL format
    if GeoTransformStr is not None:
        proj_var.GeoTransform = GeoTransformStr                                 # For GDAl - GeoTransform array

    # Projection specific parameters - http://www.unidata.ucar.edu/software/thredds/current/netcdf-java/reference/StandardCoordinateTransforms.html
    if map_pro == 1:
        # Lambert Conformal Conic

        # Required transform variables
        proj_var._CoordinateAxes = 'y x'                                            # Coordinate systems variables always have a _CoordinateAxes attribute, optional for dealing with implicit coordinate systems
        proj_var._CoordinateTransformType = "Projection"
        proj_var.standard_parallel = sr.GetProjParm("standard_parallel_1"), sr.GetProjParm("standard_parallel_2")     # Double
        proj_var.longitude_of_central_meridian = sr.GetProjParm("central_meridian")     # Double. Necessary in combination with longitude_of_prime_meridian?
        proj_var.latitude_of_projection_origin = sr.GetProjParm("latitude_of_origin")   # Double

        # Optional tansform variable attributes
        proj_var.false_easting = sr.GetProjParm("false_easting")                # Double  Always in the units of the x and y projection coordinates
        proj_var.false_northing = sr.GetProjParm("false_northing")              # Double  Always in the units of the x and y projection coordinates
        proj_var.earth_radius = sphere_radius                                   # OPTIONAL. Parameter not read by Esri. Default CF sphere: 6371.229 km.
        proj_var.semi_major_axis = sphere_radius                                # Added 10/13/2017 by KMS to match GDAL format
        proj_var.inverse_flattening = float(0)                                  # Added 10/13/2017 by KMS to match GDAL format: Double - optional Lambert Conformal Conic parameter

    elif map_pro == 2:
        # Polar Stereographic

        # Required transform variables
        proj_var._CoordinateAxes = 'y x'                                            # Coordinate systems variables always have a _CoordinateAxes attribute, optional for dealing with implicit coordinate systems
        proj_var._CoordinateTransformType = "Projection"
        proj_var.longitude_of_projection_origin = sr.GetProjParm("longitude_of_origin")   # Double - proj_var.straight_vertical_longitude_from_pole = ''
        proj_var.latitude_of_projection_origin = sr.GetProjParm("latitude_of_origin")     # Double
        proj_var.scale_factor_at_projection_origin = sr.GetProjParm("scale_factor")      # Double

        # Optional tansform variable attributes
        proj_var.false_easting = sr.GetProjParm("false_easting")                         # Double  Always in the units of the x and y projection coordinates
        proj_var.false_northing = sr.GetProjParm("false_northing")                       # Double  Always in the units of the x and y projection coordinates
        proj_var.earth_radius = sphere_radius                                   # OPTIONAL. Parameter not read by Esri. Default CF sphere: 6371.229 km.
        proj_var.semi_major_axis = sphere_radius                                # Added 10/13/2017 by KMS to match GDAL format
        proj_var.inverse_flattening = float(0)                                  # Added 10/13/2017 by KMS to match GDAL format: Double - optional Lambert Conformal Conic parameter

    elif map_pro == 3:
        # Mercator

        # Required transform variables
        proj_var._CoordinateAxes = 'y x'                                            # Coordinate systems variables always have a _CoordinateAxes attribute, optional for dealing with implicit coordinate systems
        proj_var._CoordinateTransformType = "Projection"
        proj_var.longitude_of_projection_origin = sr.GetProjParm("central_meridian")   # Double
        proj_var.latitude_of_projection_origin = sr.GetProjParm("latitude_of_origin")     # Double
        proj_var.standard_parallel = sr.GetProjParm("standard_parallel_1")                # Double
        proj_var.earth_radius = sphere_radius                                   # OPTIONAL. Parameter not read by Esri. Default CF sphere: 6371.229 km.
        proj_var.semi_major_axis = sphere_radius                                # Added 10/13/2017 by KMS to match GDAL format
        proj_var.inverse_flattening = float(0)                                  # Added 10/13/2017 by KMS to match GDAL format: Double - optional Lambert Conformal Conic parameter

    elif map_pro == 6:
        # Cylindrical Equidistant or rotated pole

        #http://cfconventions.org/Data/cf-conventions/cf-conventions-1.6/build/cf-conventions.html#appendix-grid-mappings
        # Required transform variables
        #proj_var.grid_mapping_name = "latitude_longitude"                      # or "rotated_latitude_longitude"

        #print('        Cylindrical Equidistant projection not supported.')
        #raise SystemExit
        pass                                                                    # No extra parameters needed for latitude_longitude

    # Added 10/13/2017 by KMS to accomodate alternate datums
    elif map_pro == 0:
        proj_var._CoordinateAxes = 'lat lon'
        proj_var.semi_major_axis = sr.GetSemiMajor()
        proj_var.semi_minor_axis =  sr.GetSemiMinor()
        proj_var.inverse_flattening = sr.GetInvFlattening()
        pass

    # Global attributes related to CF-netCDF
    rootgrp.Conventions = CFConv                                                # Maybe 1.0 is enough?
    return rootgrp

def get_projection_from_raster(in_raster):
    ''' Get projection from input raster and return.'''
    proj = osr.SpatialReference()
    proj.ImportFromWkt(in_raster.GetProjectionRef())
    return proj

def ReprojectCoords(xcoords, ycoords, src_srs, tgt_srs):
    '''
    Adapted from:
        https://gis.stackexchange.com/questions/57834/how-to-get-raster-corner-coordinates-using-python-gdal-bindings
     Reproject a list of x,y coordinates.
    '''
    tic1 = time.time()

    # Setup coordinate transform
    transform = osr.CoordinateTransformation(src_srs, tgt_srs)

    ravel_x = numpy.ravel(xcoords)
    ravel_y = numpy.ravel(ycoords)
    trans_x = numpy.zeros(ravel_x.shape, ravel_x.dtype)
    trans_y = numpy.zeros(ravel_y.shape, ravel_y.dtype)

    for num,(x,y) in enumerate(zip(ravel_x, ravel_y)):
        x1,y1,z = transform.TransformPoint(x,y)
        trans_x[num] = x1
        trans_y[num] = y1

    # reshape transformed coordinate arrays of the same shape as input coordinate arrays
    trans_x = trans_x.reshape(*xcoords.shape)
    trans_y = trans_y.reshape(*ycoords.shape)
    print('Completed transforming coordinate pairs [{0}] in {1: 3.2f} seconds.'.format(num, time.time()-tic1))
    return trans_x, trans_y

def create_CF_NetCDF(grid_obj, rootgrp, projdir, addLatLon=False, notes='', addVars=[], latArr=None, lonArr=None):
    """This function will create the netCDF file with CF conventions for the grid
    description. Valid output formats are 'GEOGRID', 'ROUTING_GRID', and 'POINT'.
    The output NetCDF will have the XMAP/YMAP created for the x and y variables
    and the LATITUDE and LONGITUDE variables populated from the XLAT_M and XLONG_M
    variables in the GEOGRID file or in the case of the routing grid, populated
    using the getxy function."""

    tic1 = time.time()
    print('Creating CF-netCDF File.')

    # Build Esri WKT Projection string to store in CF netCDF file
    projEsri = grid_obj.proj.Clone()                                            # Copy the SRS
    projEsri.MorphToESRI()                                                      # Alter the projection to Esri's representation of a coordinate system
    PE_string = projEsri.ExportToWkt().replace("'", '"')                        # INVESTIGATE - this somehow may provide better compatability with Esri products?
    print('    Esri PE String: {0}'.format(PE_string))

    # Find name for the grid mapping
    if CF_projdict.get(grid_obj.map_pro) is not None:
        grid_mapping = CF_projdict[grid_obj.map_pro]
        print('    Map Projection of input raster : {0}'.format(grid_mapping))
    else:
        grid_mapping = 'crs'                                                    # Added 10/13/2017 by KMS to generalize the coordinate system variable names
        print('    Map Projection of input raster (not a WRF projection): {0}'.format(grid_mapping))

    # Create Dimensions
    dim_y = rootgrp.createDimension('y', grid_obj.nrows)
    dim_x = rootgrp.createDimension('x', grid_obj.ncols)
    print('    Dimensions created after {0: 3.2f} seconds.'.format(time.time()-tic1))

    # Create coordinate variables
    var_y = rootgrp.createVariable('y', 'f8', 'y')                              # (64-bit floating point)
    var_x = rootgrp.createVariable('x', 'f8', 'x')                              # (64-bit floating point)

    # Must handle difference between ProjectionCoordinateSystem and LatLonCoordinateSystem
    if grid_obj.proj.IsGeographic():
        if crsVarname:
            CoordSysVarName = crsVar
        else:
            CoordSysVarName = "LatLonCoordinateSystem"

        # Set variable attributes
        #var_y.standard_name = ''
        #var_x.standard_name = ''
        var_y.long_name = "latitude coordinate"
        var_x.long_name = "longitude coordinate"
        var_y.units = "degrees_north"
        var_x.units = "degrees_east"
        var_y._CoordinateAxisType = "Lat"
        var_x._CoordinateAxisType = "Lon"

    elif grid_obj.proj.IsProjected():
        if crsVarname:
            CoordSysVarName = crsVar
        else:
            CoordSysVarName = "ProjectionCoordinateSystem"
        #proj_units = sr.linearUnitName.lower()                                  # sr.projectionName wouldn't work for a GEOGCS
        proj_units = 'm'                                                        # Change made 11/3/2016 by request of NWC

        # Set variable attributes
        var_y.standard_name = 'projection_y_coordinate'
        var_x.standard_name = 'projection_x_coordinate'
        var_y.long_name = 'y coordinate of projection'
        var_x.long_name = 'x coordinate of projection'
        var_y.units = proj_units                                                # was 'meter', now 'm'
        var_x.units = proj_units                                                # was 'meter', now 'm'
        var_y._CoordinateAxisType = "GeoY"                                      # Use GeoX and GeoY for projected coordinate systems only
        var_x._CoordinateAxisType = "GeoX"                                      # Use GeoX and GeoY for projected coordinate systems only
        var_y.resolution = float(abs(grid_obj.DY))                              # Added 11/3/2016 by request of NWC
        var_x.resolution = float(grid_obj.DX)                                   # Added 11/3/2016 by request of NWC

        # Build coordinate reference system variable
        rootgrp = add_CRS_var(rootgrp, grid_obj.proj, grid_obj.map_pro, CoordSysVarName, grid_mapping, PE_string, grid_obj.GeoTransformStr())

    # For prefilling additional variables and attributes on the same 2D grid, given as a list [[<varname>, <vardtype>, <long_name>],]
    for varinfo in addVars:
        ncvar = rootgrp.createVariable(varinfo[0], varinfo[1], ('y', 'x'))
        ncvar.esri_pe_string = PE_string
        ncvar.grid_mapping = CoordSysVarName
        #ncvar.long_name = varinfo[2]
        #ncvar.units = varinfo[3]

    # Get x and y variables for the netCDF file
    xmap, ymap = grid_obj.getxy()                                               # Get coordinates as numpy array
    var_y[:] = ymap[:,0]                                                        # Assumes even spacing in y across domain
    var_x[:] = xmap[0,:]                                                        # Assumes even spacing in x across domain
    ymap = xmap = None
    del ymap, xmap
    print('    Coordinate variables and variable attributes set after {0: 3.2f} seconds.'.format(time.time()-tic1))

    if addLatLon == True:
        print('    Proceeding to add LATITUDE and LONGITUDE variables after {0: 8.2f} seconds.'.format(time.time()-tic1))

        # Populate this file with 2D latitude and longitude variables
        # Latitude and Longitude variables (WRF)
        lat_WRF = rootgrp.createVariable('LATITUDE', 'f4', ('y', 'x'))          # (32-bit floating point)
        lon_WRF = rootgrp.createVariable('LONGITUDE', 'f4', ('y', 'x'))         # (32-bit floating point)
        lat_WRF.long_name = 'latitude coordinate'                               # 'LATITUDE on the WRF Sphere'
        lon_WRF.long_name = 'longitude coordinate'                              # 'LONGITUDE on the WRF Sphere'
        lat_WRF.units = "degrees_north"
        lon_WRF.units = "degrees_east"
        lat_WRF._CoordinateAxisType = "Lat"
        lon_WRF._CoordinateAxisType = "Lon"
        lat_WRF.grid_mapping = CoordSysVarName                                  # This attribute appears to be important to Esri
        lon_WRF.grid_mapping = CoordSysVarName                                  # This attribute appears to be important to Esri
        lat_WRF.esri_pe_string = PE_string
        lon_WRF.esri_pe_string = PE_string

        # Missing value attribute not needed yet
        #missing_val = numpy.finfo(numpy.float32).min                            # Define missing data variable based on numpy
        #lat_WRF.missing_value = missing_val                                     # Float sys.float_info.min?
        #lon_WRF.missing_value = missing_val                                     # Float sys.float_info.min?

        '''Adding the Esri PE String in addition to the CF grid mapping attributes
        is very useful. Esri will prefer the PE string over other CF attributes,
        allowing a spherical datum to be defined. Esri can interpret the coordinate
        system variable alone, but will assume the datum is WGS84. This cannot be
        changed except when using an Esri PE String.'''

        ##    # Create a new coordinate system variable
        ##    LatLonCoordSysVarName = "LatLonCoordinateSystem"
        ##    latlon_var = rootgrp.createVariable(LatLonCoordSysVarName, 'S1')            # (Scalar Char variable)
        ##    latlon_var._CoordinateAxes = 'LATITUDE LONGITUDE'                           # Coordinate systems variables always have a _CoordinateAxes attribute

        # Data variables need _CoodinateSystems attribute
        lat_WRF._CoordinateAxisType = "Lat"
        lon_WRF._CoordinateAxisType = "Lon"
        lat_WRF._CoordinateSystems = CoordSysVarName
        lon_WRF._CoordinateSystems = CoordSysVarName
        ##    lat_WRF._CoordinateSystems = "%s %s" %(CoordSysVarName, LatLonCoordSysVarName)        # For specifying more than one coordinate system
        ##    lon_WRF._CoordinateSystems = "%s %s" %(CoordSysVarName, LatLonCoordSysVarName)        # For specifying more than one coordinate system

        # Populate netCDF variables using input numpy arrays
        lat_WRF[:] = latArr
        lon_WRF[:] = lonArr
        print('    LATITUDE and LONGITUDE variables and variable attributes set after {0: 3.2f} seconds.'.format(time.time()-tic1))

    # Global attributes
    rootgrp.GDAL_DataType = 'Generic'
    rootgrp.Source_Software = 'WRF-Hydro GIS Pre-processor {0}'.format(PpVersion)
    rootgrp.proj4 = grid_obj.proj4                                              # Added 3/16/2018 (KMS) to avoid a warning in WRF-Hydro output
    rootgrp.history = 'Created {0}'.format(time.ctime())
    rootgrp.processing_notes = notes
    rootgrp.spatial_ref = PE_string                                             # For GDAl
    print('    netCDF global attributes set after {0: 3.2f} seconds.'.format(time.time()-tic1))

    # Return the netCDF file to the calling script
    return rootgrp, grid_mapping

### Function to reclassify values in a raster
##def reclassifyRaster(array, thresholdDict):
##    '''
##    Apply a dictionary of thresholds to an array for reclassification.
##    This function may be made more complicated as necessary
##    '''
##    # Reclassify array using bounds and new classified values
##    new_arr = array.copy()
##    for newval, oldval in thresholdDict.iteritems():
##        mask = numpy.where(array==oldval)
##        new_arr[mask] = newval
##    del array
##    return new_arr
##
### Function to calculate statistics on a raster using gdalinfo command-line
##def calcStats(inRaster):
##    print('    Calculating statistics on %s' %inRaster)
##    subprocess.call('gdalinfo -stats %s' %inRaster, shell=True)
##
##def apply_threshold(array, thresholdDict):
##    '''
##    Apply a dictionary of thresholds to an array for reclassification.
##    This function may be made more complicated as necessary
##    '''
##
##    # Reclassify array using bounds and new classified values
##    for newval, bounds in thresholdDict.iteritems():
##        mask = numpy.where((array > bounds[0]) & (array <= bounds[1]))          # All values between bounds[0] and bounds[1]
##        array[mask] = newval
##    return array

def build_GW_Basin_Raster(in_nc, projdir, in_method, strm, fdir, grid_obj, in_Polys=None):
    '''
    10/10/2017:
    This function was added to build the groundwater basins raster using a variety
    of methods. The result is a raster on the fine-grid which can be used to create
    groundwater bucket parameter tables in 1D and 2D for input to WRF-Hydro.
    '''

    tic1 = time.time()
    print('Beginning to build 2D groundwater basin inputs')
    print('  Building groundwater inputs using {0}'.format(in_method))

    # Determine which method will be used to generate groundwater bucket grid
    if in_method == 'FullDom basn_msk variable':
        print('    Reading Fulldom_hires for basn_msk variable.')

        # Create a raster layer from the netCDF
        rootgrp = netCDF4.Dataset(in_nc, 'r')                                      # Read-only on FullDom file
        GWBasns = numpy_to_Raster(rootgrp.variables['basn_msk'][:], grid_obj.proj, grid_obj.DX, grid_obj.DY, grid_obj.x00, grid_obj.y00)
        rootgrp.close()
        del rootgrp

    elif in_method == 'FullDom LINKID local basins':
        print('    Generating LINKID grid and channel vector shapefile.')

        # Whitebox options for running Whitebox in a full workflow
        wbt = WhiteboxTools()
        esri_pntr = True
        wbt.verbose = False
        wbt.work_dir = projdir

        # Temporary outputs
        streams = os.path.basename(strm)
        dir_d8 = os.path.basename(fdir)

        # Build sub-basins, one for each reach
        wbt.subbasins(dir_d8, streams, sub_basins, esri_pntr=esri_pntr)

        # Create raster object from output
        sub_basins_file = os.path.join(projdir, sub_basins)
        GWBasns = gdal.Open(sub_basins_file, gdalconst.GA_ReadOnly)

    elif in_method == 'Polygon Shapefile or Feature Class':
        print('    Groundwater  polygon shapefile input: {0}'.format(in_Polys))

        # Setup empty output
        #GWBasns = gdal.GetDriverByName('Mem').Create('poly_basins', DX, DY, 1, gdal.GDT_Int32)
        #GWBasns.SetProjection(grid_obj.WKT)
        #GWBasns.SetGeoTransform((xMin, DX, 0, yMax, 0, DY))
        #band = GWBasns.GetRasterBand(1)
        #band.SetNoDataValue(NoDataVal)
        #band.FlushCache()

        # Read polygon geometry
        #in_vect = ogr.Open(in_Polys)
        #in_layer = in_vect.GetLayer()

        # Resolve basins on the fine grid
        #gdal.RasterizeLayer(GWBasns, [1], in_layer, options=["ATTRIBUTE=FID"])
        #in_vect = in_layer = band = None

        # Open raster which will be used as a template
        template_raster = gdal.Open(strm, gdalconst.GA_ReadOnly)

        GWBasns = FeatToRaster(in_Polys, template_raster, 'FID', gdal.GDT_Int32, NoData=NoDataVal)
        template_raster = None

    print('Finished building groundwater basin grids in {0: 3.2f} seconds'.format(time.time()-tic1))
    return GWBasns

def build_GWBASINS_nc(GW_BUCKS, out_dir, grid_obj):
    '''
    5/17/2017: This function will build the 2-dimensional groundwater bucket
    grid in netCDF format.
    '''

    tic1 = time.time()
    out_file = os.path.join(out_dir, GWGRID_nc)
    varList2D = [['BASIN', 'i4', 'Basin ID corresponding to GWBUCKPARM table values']]

    # Build output 2D GWBASINS netCDF file
    rootgrp = netCDF4.Dataset(out_file, 'w', format=outNCType)
    rootgrp, grid_mapping = create_CF_NetCDF(grid_obj, rootgrp, out_dir, addLatLon=False, notes='', addVars=varList2D)
    del grid_mapping

    # Array size check
    GWBasns_arr = BandReadAsArray(GW_BUCKS.GetRasterBand(1))
    print('    NC dimensions: {0}, {1}'.format(len(rootgrp.dimensions['y']), len(rootgrp.dimensions['x'])))
    print('    GWBUCKS array dimensions: {0}, {1}'.format(GWBasns_arr.shape[0], GWBasns_arr.shape[1]))

    # Add groundwater buckets to the file (flip UP-DOWN?)
    ncvar = rootgrp.variables[varList2D[0][0]]                                  # 'BASIN'
    ncvar[:] = GWBasns_arr[:]                                                   # Populate variable with groundwater bucket array
    rootgrp.close()
    print('    Process: {0} completed without error'.format(out_file))
    print('    Finished building groundwater grid file in {0: 3.2f} seconds'.format(time.time()-tic1))
    del GW_BUCKS, GWBasns_arr, varList2D, ncvar, rootgrp
    return

def build_GWBUCKPARM(out_dir, cat_areas, cat_comids):
    '''
    5/17/2017: This function will build the groundwater bucket parameter table.
               Currently, only netCDF output format is available.
    '''
    tic1 = time.time()
    Community = True                                                            # Switch to provide Community WRF-Hydro GWBUCKPARM outputs

    # Produce output in NetCDF format (binary and much faster to produce)
    out_file = os.path.join(out_dir, GW_nc)                                     # Groundwater bucket parameter table path and filename
    rootgrp = netCDF4.Dataset(out_file, 'w', format=outNCType)

    # Create dimensions and set other attribute information
    dim1 = 'feature_id'
    dim = rootgrp.createDimension(dim1, len(cat_comids))

    # Create fixed-length variables
    Basins = rootgrp.createVariable('Basin', 'i4', (dim1))                  # Variable (32-bit signed integer)
    coeffs = rootgrp.createVariable('Coeff', 'f4', (dim1))                  # Variable (32-bit floating point)
    Expons = rootgrp.createVariable('Expon', 'f4', (dim1))                  # Variable (32-bit floating point)
    Zmaxs = rootgrp.createVariable('Zmax', 'f4', (dim1))                    # Variable (32-bit floating point)
    Zinits = rootgrp.createVariable('Zinit', 'f4', (dim1))                  # Variable (32-bit floating point)
    Area_sqkms = rootgrp.createVariable('Area_sqkm', 'f4', (dim1))          # Variable (32-bit floating point)
    ComIDs = rootgrp.createVariable('ComID', 'i4', (dim1))                  # Variable (32-bit signed integer)

    # Set variable descriptions
    Basins.long_name = 'Basin monotonic ID (1...n)'
    coeffs.long_name = 'Coefficient'
    Expons.long_name = 'Exponent'
    Zmaxs.long_name = 'Bucket height'
    Zinits.long_name = 'Initial height of water in bucket'
    Area_sqkms.long_name = 'Basin area in square kilometers'
    if Community:
        ComIDs.long_name = 'Catchment Gridcode'
    else:
        ComIDs.long_name = 'NHDCatchment FEATUREID (NHDFlowline ComID)'     # For NWM
    Zmaxs.units = 'mm'
    Zinits.units = 'mm'
    Area_sqkms.units = 'km2'

    # Fill in global attributes
    rootgrp.featureType = 'point'                                           # For compliance
    rootgrp.history = 'Created {0}'.format(time.ctime())

    # Fill in variables
    Basins[:] = cat_comids                                                  #Basins[:] = numpy.arange(1,cat_comids.shape[0]+1)
    coeffs[:] = coeff
    Expons[:] = expon
    Zmaxs[:] = zmax
    Zinits[:] = zinit
    Area_sqkms[:] = numpy.array(cat_areas)
    ComIDs[:] = numpy.array(cat_comids)

    # Close file
    rootgrp.close()
    print('    Created output bucket parameter table (.nc): {0}.'.format(out_file))
    del rootgrp, dim1, dim, Basins, coeffs, Expons, Zmaxs, Zinits, Area_sqkms, ComIDs, out_file

    # Print statements and return
    print('  Finished building groundwater bucket parameter table in {0: 3.2f} seconds.'.format(time.time()-tic1))
    del tic1, Community, cat_areas, cat_comids
    return

def build_GW_buckets(out_dir, GWBasns, grid_obj, Grid=True):
    '''
    5/17/2017: This function will build the groundwater bucket grids and parameter
               tables.

    1) A set of basins must be provided. This is a grid of watershed pixels, in
       which each value on the grid corresponds to a basin.

    Build Options:
        1) Build option 1 will biuld the groundwater buckets from ...

    NOTES:
       * Groundwater buckets are currently resolved on the LSM (coarse/GEOGRID)
         grid. In the future this may change.
       * The ID values for groundwater buckets must be numbered 1...n, and will
         not directly reflect the COMID values of individual basins or pour points.
         Much like the LAKEPARM and LAKEGRID values, a mapping must be made between
         input basins/lakes and the outputs using the shapefiles/parameter tables
         output by these tools.
    '''

    tic1 = time.time()
    print('Beginning to build groundwater inputs')

    # Read basin information from the array
    GWBasns_arr = BandReadAsArray(GWBasns.GetRasterBand(1))                     # Read input raster into array
    ndv = GWBasns.GetRasterBand(1).GetNoDataValue()                             # Obtain nodata value
    UniqueVals = numpy.unique(GWBasns_arr[GWBasns_arr!=ndv])                    # Array to store the basin ID values in the fine-grid groundwater basins
    UniqueVals = UniqueVals[UniqueVals>=0]                                      # Remove NoData, removes potential noData values (-2147483647, -9999)
    print('    Found {0} basins in the watershed grid'.format(UniqueVals.shape[0]))
    del UniqueVals, GWBasns_arr

    # Resample fine-grid groundwater basins to coarse grid
    GW_BUCKS = grid_obj.project_to_model_grid(GWBasns, resampling=gdal.GRA_NearestNeighbour)
    del GWBasns

    # Re-assign basin IDs to 1...n because sometimes the basins get lost when converting to coarse grid
    band = GW_BUCKS.GetRasterBand(1)
    GWBasns_arr2 = BandReadAsArray(band)                                        # Create array from raster
    ndv = band.GetNoDataValue()                                                 # Obtain nodata value
    GWBasns_arr2[GWBasns_arr2==ndv] = NoDataVal                                 # Ensure all non-basin areas are NoData
    UniqueVals2 = numpy.unique(GWBasns_arr2[:])                                 # Get the unique values, including nodata
    GW_BUCKS = band = ndv = None                                                      # Destroy the resampled-to-coarse-grid groundwater basin raster
    print('    Found {0} basins (potentially including nodata values) in the file after resampling to the coarse grid.'.format(UniqueVals2.shape[0]))

    '''Because we resampled to the coarse grid, we lost some basins. Thus, we need to
    re-assign basin ID values to conform to the required 1...n groundwater basin
    ID assignment scheme.'''
    # Fast replace loop from https://stackoverflow.com/questions/3403973/fast-replacement-of-values-in-a-numpy-array
    # This method ensures that any nodata values are issued a 0 index in sort_idx
    sort_idx = numpy.argsort(UniqueVals2)                                       # Index of each unique value, 0-based
    idx = numpy.searchsorted(UniqueVals2, GWBasns_arr2, sorter=sort_idx)        # 2D array of index values against GWBasns_arr2
    del GWBasns_arr2, sort_idx                                                  # Free up memory

    # This method requires the nodata value to be issued a 0 index in sort_idx and idx
    to_values = numpy.arange(UniqueVals2.size)                                  # 0..n values to be substituted, 0 in place of NoDataVal
    GWBasns_arr3 = to_values[idx]                                               # Same as to_values[sort_idx][idx]
    if numpy.where(UniqueVals2==NoDataVal)[0].shape[0] > 0:
        new_ndv = int(to_values[numpy.where(UniqueVals2==NoDataVal)[0]][0])         # Obtain the newly-assigned nodatavalue
    else:
        new_ndv = NoDataVal
        GWBasns_arr3+=1                                                         # Add one so that the basin IDs will be 1...n rather than 0...n when there are no nodata values in the grid
    GWBasns_arr3[GWBasns_arr3==new_ndv] = NoDataVal
    del UniqueVals2

    # Build rasters and arrays to create the NC or ASCII outputs
    GW_BUCKS = numpy_to_Raster(GWBasns_arr3, grid_obj.proj, grid_obj.DX, grid_obj.DY, grid_obj.x00, grid_obj.y00)
    del GWBasns_arr3, idx, to_values, new_ndv

    # If requested, create 2D gridded bucket parameter table
    if Grid == True:
        build_GWBASINS_nc(GW_BUCKS, out_dir, grid_obj)

    # Alternate method to obtain IDs - read directly from raster attribute table
    print('    Calculating size and ID parameters for basin polygons.')
    GW_BUCKS_arr = BandReadAsArray(GW_BUCKS.GetRasterBand(1))
    cat_comids = numpy.unique(GW_BUCKS_arr[:]).tolist()
    pixel_counts = [GW_BUCKS_arr[GW_BUCKS_arr==item].sum() for item in cat_comids]
    cat_areas = [float((item*(grid_obj.DX**2))/1000000) for item in pixel_counts]  # Assumes DX is in units of meters
    GW_BUCKS = None
    del GW_BUCKS, GW_BUCKS_arr, pixel_counts

    # Build the groundwater bucket parameter table in netCDF format
    build_GWBUCKPARM(out_dir, cat_areas, cat_comids)

    # Clean up and return
    del cat_comids, cat_areas
    print('Finished building groundwater parameter files in {0: 3.2f} seconds'.format(time.time()-tic1))
    return

def return_raster_array(in_file):
    '''
    Read a GDAL-compatible raster file from disk and return the array of raster
    values as well as the nodata value.
    '''
    ds = gdal.Open(in_file, gdalconst.GA_ReadOnly)
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()
    ndv = band.GetNoDataValue()                                                 # Obtain nodata value
    ds = band = None
    return arr, ndv

def getxy(ds):
    """
    This function will use the affine transformation (GeoTransform) to produce an
    array of X and Y 1D arrays. Note that the GDAL affine transformation provides
    the grid cell coordinates from the upper left corner. This is typical in GIS
    applications. However, WRF uses a south_north ordering, where the arrays are
    written from the bottom to the top.

    The input raster object will be used as a template for the output rasters.
    """
    print('    Starting Process: Building to XMap/YMap')
    nrows = ds.RasterYSize
    ncols = ds.RasterXSize
    xMin, DX, xskew, yMax, yskew, DY = ds.GetGeoTransform()
    del ds, xskew, yskew

    # Build i,j arrays
    j = numpy.arange(nrows) + float(0.5)                                        # Add 0.5 to estimate coordinate of grid cell centers
    i = numpy.arange(ncols) + float(0.5)                                        # Add 0.5 to estimate coordinate of grid cell centers

    # col, row to x, y   From https://www.perrygeo.com/python-affine-transforms.html
    x = (i * DX) + xMin
    y = (j * DY) + yMax
    del i, j, DX, DY, xMin, yMax

    # Create 2D arrays from 1D
    xmap = numpy.repeat(x[numpy.newaxis, :], y.shape, 0)
    ymap = numpy.repeat(y[:, numpy.newaxis], x.shape, 1)
    del x, y
    print('    Conversion of input raster to XMap/YMap completed without error.')
    return xmap, ymap

def remove_file(in_file):
    '''
    Remove any individual file using os.remove().
    '''
    if os.path.exists(in_file):
        os.remove(in_file)
    return

def WB_functions(rootgrp, indem, projdir, threshold, ovroughrtfac_val, retdeprtfac_val, lksatfac_val):
    """
    This function is intended to produce the hydroglocial DEM corrections and derivitive
    products using the Whitebox tools suite.
    """

    tic1 = time.time()
    print('Step 4 initiated...')

    # Whitebox options for running Whitebox in a full workflow
    wbt = WhiteboxTools()
    esri_pntr = True
    zero_background = True
    wbt.verbose = False
    wbt.work_dir = projdir

    # Temporary output files
    flow_acc = "flow_acc.tif"
    fac_type = 'cells'                          # ['cells', 'sca' (default), ca']

    # Perform Fill, Flow Direction, and Flow Accumulation in one step
    wbt.flow_accumulation_full_workflow(indem, fill_pits, dir_d8, flow_acc, out_type=fac_type, esri_pntr=esri_pntr)

    # Process: Fill DEM
    fill_pits_file = os.path.join(projdir, fill_pits)
    fill_arr, ndv = return_raster_array(fill_pits_file)                   # ZLIMIT?! Is the output a Float?
    fill_arr[fill_arr==ndv] = NoDataVal                                         # Replace raster NoData with WRF-Hydro NoData value
    rootgrp.variables['TOPOGRAPHY'][:] = fill_arr
    print('    Process: TOPOGRAPHY written to output netCDF.')
    #remove_file(fill_pits_file)                                                 # Delete temporary file
    del fill_arr, ndv       #, fill_pits_file

    # Process: Flow Direction
    dir_d8_file = os.path.join(projdir, dir_d8)
    fdir_arr, ndv = return_raster_array(dir_d8_file)
    rootgrp.variables['FLOWDIRECTION'][:] = fdir_arr                    # INT DTYPE?
    print('    Process: FLOWDIRECTION written to output netCDF.')
    del fdir_arr, ndv

    # Process: Flow Accumulation (intermediate
    flow_acc_file = os.path.join(projdir, flow_acc)
    flac_arr, ndv = return_raster_array(flow_acc_file)                # FLOAT DTYPE?
    rootgrp.variables['FLOWACC'][:] = flac_arr
    print('    Process: FLOWACC written to output netCDF.')
    del flac_arr, ndv

    # Create stream channel raster according to threshold
    wbt.extract_streams(flow_acc, streams, threshold, zero_background=False)
    streams_file = os.path.join(projdir, streams)
    strm_arr, ndv = return_raster_array(streams_file)                # FLOAT DTYPE?
    strm_arr[strm_arr==1] = 0
    strm_arr[strm_arr==ndv] = NoDataVal
    rootgrp.variables['CHANNELGRID'][:] = strm_arr
    print('    Process: CHANNELGRID written to output netCDF.')
    del strm_arr, ndv, flow_acc

    # Process: Stream Order
    #wbt.strahler_stream_order(dir_d8, streams, strahler, esri_pntr=esri_pntr, zero_background=zero_background)
    wbt.strahler_stream_order(dir_d8, streams, strahler, esri_pntr=esri_pntr, zero_background=False)
    strahler_file = os.path.join(projdir, strahler)
    strahler_arr, ndv = return_raster_array(strahler_file)                # FLOAT DTYPE?

    # -9999 does not fit in the 8-bit types, so it gets put in as -15 by netCDF4 for some reason
    strahler_arr[strahler_arr==ndv] = NoDataVal
    rootgrp.variables['STREAMORDER'][:] = strahler_arr
    print('    Process: STREAMORDER written to output netCDF.')
    remove_file(strahler_file)
    del strahler_arr, ndv, strahler_file

    # Create initial constant raster of value retdeprtfac_val
    rootgrp.variables['RETDEPRTFAC'][:] = float(retdeprtfac_val)
    print('    Process: RETDEPRTFAC written to output netCDF.')

    # Create initial constant raster of ovroughrtfac_val
    rootgrp.variables['OVROUGHRTFAC'][:] = float(ovroughrtfac_val)
    print('    Process: OVROUGHRTFAC written to output netCDF.')

    # Create initial constant raster of LKSATFAC
    rootgrp.variables['LKSATFAC'][:] = float(lksatfac_val)
    print('    Process: LKSATFAC written to output netCDF.')

    # We will assume that no forecast points, basin masks, or lakes are provided
    rootgrp.variables['frxst_pts'][:] = NoDataVal
    rootgrp.variables['basn_msk'][:] = NoDataVal
    rootgrp.variables['LAKEGRID'][:] = NoDataVal

    print('    Step 4 completed without error in {0: 3.2f} seconds.'.format(time.time()-tic1))
    return rootgrp, dir_d8_file, flow_acc_file, streams_file, fill_pits_file

def alter_GT(GT, regridFactor):
    '''
    This function will alter the resolution of a raster's affine transformation,
    assuming that the extent and CRS remain unchanged.
    '''
    # Georeference geogrid file
    GeoTransform = list(GT)
    DX = GT[1]/float(regridFactor)
    DY = GT[5]/float(regridFactor)
    GeoTransform[1] = DX
    GeoTransform[5] = DY
    GeoTransformStr = ' '.join([str(item) for item in GeoTransform])
    return GeoTransform, GeoTransformStr, DX, DY

def raster_extent(in_raster):
    '''
    Given a raster object, return the bounding extent [xMin, yMin, xMax, yMax]
    '''
    xMin, DX, xskew, yMax, yskew, DY = in_raster.GetGeoTransform()
    Xsize = in_raster.RasterXSize
    Ysize = in_raster.RasterYSize
    xMax = xMin + (float(Xsize)*DX)
    yMin = yMax + (float(Ysize)*DY)
    del Xsize, Ysize, xskew, yskew, DX, DY
    return [xMin, yMin, xMax, yMax]

# Coastline harmonization with a landmask
def coastlineHarmonize(maskFile, ds, outmaskFile, outDEM, minimum, waterVal=0):
    '''
    This function is designed to take a coastline mask and harmonize elevation
    values to it, such that no elevation values that are masked as water cells
    will have elevation >0, and no land cells will have an elevation < minimum.
    '''
    tic1 = time.time()

    # Read mask file for information
    refDS = gdal.Open(maskFile, gdalconst.GA_ReadOnly)
    target_ds = gdal.GetDriverByName(RasterDriver).Create(outmaskFile, ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
    DEM_ds = gdal.GetDriverByName(RasterDriver).Create(outDEM, ds.RasterXSize, ds.RasterYSize, 1, ds.GetRasterBand(1).DataType)
    CopyDatasetInfo(ds, target_ds)                                              # Copy information from input to output
    CopyDatasetInfo(ds, DEM_ds)                                                 # Copy information from input to output

    # Resample input to output
    gdal.ReprojectImage(refDS, target_ds, refDS.GetProjection(), target_ds.GetProjection(), gdalconst.GRA_NearestNeighbour)

    # Build numpy array of the mask grid and elevation grid
    maskArr = BandReadAsArray(target_ds.GetRasterBand(1))
    elevArr = BandReadAsArray(ds.GetRasterBand(1))

    # Reassign values
    ndv = ds.GetRasterBand(1).GetNoDataValue()                                  # Obtain nodata value
    mask = maskArr==1                                                           # A boolean mask of True wherever LANDMASK=1
    elevArr[elevArr==ndv] = 0                                                   # Set Nodata cells to 0
    elevArr[mask] += minimum                                                    # For all land cells, add minimum elevation
    elevArr[~mask] = waterVal                                                   # ds.GetRasterBand(1).GetNoDataValue()

    # Write to output
    band = DEM_ds.GetRasterBand(1)
    BandWriteArray(band, elevArr)
    band.SetNoDataValue(ndv)

    # Clean up
    target_ds = refDS = DEM_ds = band = None
    del maskArr, elevArr, ndv, mask
    print('    DEM harmonized with landmask in %3.2f seconds.' %(time.time()-tic1))

def CSV_to_SHP(in_csv, DriverName='MEMORY', xVar='LON', yVar='LAT', idVar='FID', toProj=None):
    tic1 = time.time()

    drv = ogr.GetDriverByName(DriverName)
    if drv is None:
        print('      {0} driver not available.'.format(DriverName))
        raise SystemExit
    else:
        data_source = drv.CreateDataSource('')

    # Read the input CSV file
    csv_arr = numpy.genfromtxt(in_csv, delimiter=',', names=True)

    # create the spatial reference for the input point CSV file, WGS84
    srs = osr.SpatialReference()
    srs.ImportFromProj4(wgs84_proj4)

    # Handle coordinate transformation
    if toProj is not None:
        # Create the spatial reference for the output
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(toProj)
        transform = osr.CoordinateTransformation(srs, out_srs)
    else:
        out_srs = srs.Clone()

    # Add the fields we're interested in
    layer = data_source.CreateLayer('frxst_FC', out_srs, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn(idVar, ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn(yVar, ogr.OFTReal))
    layer.CreateField(ogr.FieldDefn(xVar, ogr.OFTReal))
    featureDefn = layer.GetLayerDefn()

    # Process the text file and add the attributes and features to the shapefile
    for row in csv_arr:
        x = row[xVar]
        y = row[yVar]

        # Set the attributes using the values from the delimited text file
        feature = ogr.Feature(featureDefn)                               # create the feature
        feature.SetField(idVar, row[idVar])
        feature.SetField(yVar, y)
        feature.SetField(xVar, x)

        #create point geometry
        if toProj is not None:
            x,y,z = transform.TransformPoint(x,y)
            pass
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint(x,y)

        # Create the feature and set values
        feature.SetGeometry(point)
        layer.CreateFeature(feature)
        feature = point = None
        del x, y
    layer = srs = drv = None                                      # Saveand close the data source
    return data_source

# Function for using forecast points
def FeatToRaster(InputVector, inRaster, fieldname, dtype, NoData=None):
    '''
    This function will take a point shapefile and rasterize it. The point feature
    class must have a field in it with values of 1, which is an optional input
    to the RasterizeLayer function. Currently, this field is named PURPCODE. The
    result is a raster of NoData and 1 values, which is used as the "Input
    Depression Mask Grid" in TauDEM's PitRemove tool.
    '''
    # Python GDAL_RASTERIZE syntax, adatped from:
    #    https://gis.stackexchange.com/questions/212795/rasterizing-shapefiles-with-gdal-and-python

    # Open Raster input
    ds = gdal.Open(inRaster)

    # Get shapefile information
    in_vector = ogr.Open(InputVector)
    in_layer = in_vector.GetLayer()
    driver = gdal.GetDriverByName('Mem')                                        # Write to Memory
    target_ds = driver.Create('', ds.RasterXSize, ds.RasterYSize, 1, dtype)

    # Copy input raster info to output (SpatialReference, Geotransform, etc)
    CopyDatasetInfo(ds, target_ds)
    band = target_ds.GetRasterBand(1)
    if NoData is not None:
        band.SetNoDataValue(NoData)
    band.FlushCache()
    gdal.RasterizeLayer(target_ds, [1], in_layer, options=["ATTRIBUTE=%s" %fieldname])
    stats = target_ds.GetRasterBand(1).GetStatistics(0,1)                       # Calculate statistics on new raster
    return target_ds

def forecast_points(in_csv, rootgrp, bsn_msk, projdir, DX, WKT, fdir, fac, strm):
    # (in_csv, rootgrp, bsn_msk, projdir, template_raster) = (in_csv, rootgrp2, basin_mask, projdir, mosprj)

    tic1 = time.time()

    # Setup whitebox tool object and options
    wbt = WhiteboxTools()
    wbt.verbose = False
    wbt.work_dir = projdir
    esri_pntr = True

    # Setup snap tolerances for snapping forecast points to channel pixels
    snap_dist1 = int(DX)                                                        # This is to put the point on the grid only. One pixel tolerance
    snap_dist2 = int(DX * walker)                                               # This is to search for the within a distance

    # Make feature layer from CSV
    print('    Forecast points provided and basins being delineated.')
    frxst_FC = os.path.join(projdir, 'Temp_Frxst_Pts.shp')
    ds = CSV_to_SHP(in_csv, DriverName='MEMORY', xVar='LON', yVar='LAT', idVar='FID', toProj=WKT)  # In-memory features
    out_ds = ogr.GetDriverByName(VectorDriver).CopyDataSource(ds, frxst_FC)    # Copy to file on disk
    ds = out_ds = None

    # Snap pour points to channel grid within a tolerance
    wbt.jenson_snap_pour_points(frxst_FC, strm, snapPour1, snap_dist2)

    # Convert point shapefile to raster
    frxst_raster = FeatToRaster(frxst_FC, fac, 'FID', gdal.GDT_Int32, NoData=NoDataVal)
    frxst_raster_arr = BandReadAsArray(frxst_raster.GetRasterBand(1))
    frxst_raster = None
    frxst_raster_arr[frxst_raster_arr==0] = NoDataVal                           # Replace 0 with WRF-Hydro NoData value
    rootgrp.variables['frxst_pts'][:] = frxst_raster_arr
    print('    Process: frxst_pts written to output netCDF.')
    del frxst_raster_arr

    # Snap pour points to flow accumulation grid within a tolerance
    wbt.snap_pour_points(frxst_FC, fac, snapPour2, snap_dist2)

    # Delineate above points
    watershed_file = os.path.join(projdir, watersheds)
    wbt.watershed(fdir, snapPour2, watershed_file, esri_pntr=esri_pntr)
    watershed_arr, ndv = return_raster_array(watershed_file)
    watershed_arr[watershed_arr==ndv] = NoDataVal                               # Replace raster NoData with WRF-Hydro NoData value
    rootgrp.variables['basn_msk'][:] = watershed_arr
    print('    Process: basn_msk written to output netCDF.')
    remove_file(watershed_file)                                                 # Delete fac from disk
    del ndv, watershed_file

    # Delete temporary point shapefiles
    ogr.GetDriverByName(VectorDriver).DeleteDataSource(frxst_FC)
    ogr.GetDriverByName(VectorDriver).DeleteDataSource(os.path.join(projdir, snapPour1))
    ogr.GetDriverByName(VectorDriver).DeleteDataSource(os.path.join(projdir, snapPour2))

    # Set mask for future raster output
    if bsn_msk:
        print('    Channelgrid will be masked to basins.')
        channelgrid_arr = rootgrp.variables['CHANNELGRID'][:]

        # Converts channelgrid values inside basins to 0, outside to -1
        channelgrid_arr[numpy.logical_and(watershed_arr>=0, channelgrid_arr!=NoDataVal)] = 0
        channelgrid_arr[numpy.logical_and(watershed_arr<0, channelgrid_arr!=NoDataVal)] = -1
        rootgrp.variables['CHANNELGRID'][:] = channelgrid_arr
        print('    Process: CHANNELGRID written to output netCDF.')
        del channelgrid_arr
    else:
        print('    Channelgrid will not be masked to basins.')
    del watershed_arr

    print('    Built forecast point outputs in {0: 3.2f} seconds.'.format(time.time()-tic1))
    return rootgrp

def save_raster(OutGTiff, in_raster, rows, cols, gdaltype, NoData=None):

    target_ds = gdal.GetDriverByName(RasterDriver).Create(OutGTiff, cols, rows, 1, gdaltype)

    band = in_raster.GetRasterBand(1)
    arr_out = band.ReadAsArray()                                                #Read the data into numpy array

    target_ds.SetGeoTransform(in_raster.GetGeoTransform())
    target_ds.SetProjection(in_raster.GetProjection())
    target_ds.GetRasterBand(1).WriteArray(arr_out)

    if NoData is not None:
        target_ds.GetRasterBand(1).SetNoDataValue(NoDataVal)                    # Set noData

    stats = target_ds.GetRasterBand(1).GetStatistics(0,1)                       # Calculate statistics
    #stats = target_ds.GetRasterBand(1).ComputeStatistics(0)                    # Force recomputation of statistics

    target_ds.FlushCache()                                                      #saves to disk!!
    target_ds = None
    return

def build_RouteLink(RoutingNC, order, From_To, NodeElev, Arc_To_From, Arc_From_To, NodesLL, NodesXY, Lengths, Straglers, StrOrder, sr, gageDict=None):
    '''
    8/10/2017: This function is designed to build the routiing parameter netCDF file.
                Ideally, this will be the only place the produces the file, and
                all functions wishing to write the file will reference this function.
    '''
    tic1 = time.time()

    # To create a netCDF parameter file
    rootgrp = netCDF4.Dataset(RoutingNC, 'w', format=outNCType)

    # Create dimensions and set other attribute information
    #dim1 = 'linkDim'
    dim1 = 'feature_id'
    dim2 = 'IDLength'
    dim = rootgrp.createDimension(dim1, len(order))
    gage_id = rootgrp.createDimension(dim2, 15)

    # Create fixed-length variables
    ids = rootgrp.createVariable('link', 'i4', (dim1))                          # Variable (32-bit signed integer)
    froms = rootgrp.createVariable('from','i4',(dim1))                          # Variable (32-bit signed integer)
    tos = rootgrp.createVariable('to','i4',(dim1))                              # Variable (32-bit signed integer)
    slons = rootgrp.createVariable('lon', 'f4', (dim1))                         # Variable (32-bit floating point)
    slats = rootgrp.createVariable('lat', 'f4', (dim1))                         # Variable (32-bit floating point)
    selevs = rootgrp.createVariable('alt', 'f4', (dim1))                        # Variable (32-bit floating point)
    orders = rootgrp.createVariable('order','i4',(dim1))                        # Variable (32-bit signed integer)
    Qis = rootgrp.createVariable('Qi', 'f4', (dim1))                            # Variable (32-bit floating point)
    MusKs = rootgrp.createVariable('MusK','f4',(dim1))                          # Variable (32-bit floating point)
    MusXs = rootgrp.createVariable('MusX', 'f4', (dim1))                        # Variable (32-bit floating point)
    Lengthsnc = rootgrp.createVariable('Length', 'f4', (dim1))                  # Variable (32-bit floating point)
    ns = rootgrp.createVariable('n', 'f4', (dim1))                              # Variable (32-bit floating point)
    Sos = rootgrp.createVariable('So', 'f4', (dim1))                            # Variable (32-bit floating point)
    ChSlps = rootgrp.createVariable('ChSlp', 'f4', (dim1))                      # Variable (32-bit floating point)
    BtmWdths = rootgrp.createVariable('BtmWdth','f4',(dim1))                    # Variable (32-bit floating point)
    Times = rootgrp.createVariable('time', 'f4')                                # Scalar Variable (32-bit floating point)
    geo_x = rootgrp.createVariable('x', 'f4', (dim1))                           # Variable (32-bit floating point)
    geo_y = rootgrp.createVariable('y', 'f4', (dim1))                           # Variable (32-bit floating point)
    Kcs = rootgrp.createVariable('Kchan', 'i2', (dim1))                         # Variable (16-bit signed integer)
    Gages = rootgrp.createVariable('gages', 'S1', (dim1, dim2))                 # Variable (string type character) Added 07/27/2015 - 15 character strings
    LakeDis = rootgrp.createVariable('NHDWaterbodyComID', 'i4', (dim1))         # Variable (32-bit signed integer)

    # Add CF-compliant coordinate system variable
    if pointCF:
        sr = arcpy.SpatialReference(pointSR)                                    # Build a spatial reference object
        PE_string = sr.exportToString().replace("'", '"')                       # Replace ' with " so Esri can read the PE String properly when running NetCDFtoRaster
        grid_mapping = crsVar
        rootgrp = add_CRS_var(rootgrp, sr, 0, grid_mapping, 'latitude_longitude', PE_string)

    # Set variable descriptions
    ids.long_name = 'Link ID'
    froms.long_name = 'From Link ID'
    tos.long_name = 'To Link ID'
    slons.long_name = 'longitude of the start node'
    slats.long_name = 'latitude of the start node'
    selevs.long_name = 'Elevation in meters at start node'
    orders.long_name = 'Stream order (Strahler)'
    Qis.long_name = 'Initial flow in link (CMS)'
    MusKs.long_name = 'Muskingum routing time (s)'
    MusXs.long_name = 'Muskingum weighting coefficient'
    Lengthsnc.long_name = 'Stream length (m)'
    ns.long_name = "Manning's roughness"
    Sos.long_name = 'Slope (%; drop/length)'
    ChSlps.long_name = 'Channel side slope (%; drop/length)'
    BtmWdths.long_name = 'Bottom width of channel'
    geo_x.long_name = "x coordinate of projection"
    geo_y.long_name = "y coordinate of projection"
    Kcs.long_name = "channel conductivity"
    LakeDis.long_name = 'ID of the lake element that intersects this flowline'
    Gages.long_name = 'Gage ID'

    # Variable attributes for CF compliance
    slons.units = 'degrees_east'                                                # For compliance
    slats.units = 'degrees_north'                                               # For compliance
    slons.standard_name = 'longitude'                                           # For compliance
    slats.standard_name = 'latitude'                                            # For compliance
    Times.standard_name = 'time'                                                # For compliance
    Times.long_name = 'time of measurement'                                     # For compliance
    Times.units = 'days since 2000-01-01 00:00:00'                              # For compliance
    selevs.standard_name = "height"                                             # For compliance
    selevs.units = "m"                                                          # For compliance
    selevs.positive = "up"                                                      # For compliance
    selevs.axis = "Z"                                                           # For compliance
    ids.cf_role = "timeseries_id"                                               # For compliance
    geo_x.standard_name = "projection_x_coordinate"
    geo_y.standard_name = "projection_y_coordinate"
    geo_x.units = "m"
    geo_y.units = "m"
    Kcs.units = "mm h-2"
    slons.standard_name = 'longitude'                                           # For compliance with NCO
    slats.standard_name = 'latitude'                                            # For compliance with NCO

    # Apply grid_mapping and coordinates attributes to all variables
    for varname, ncVar in rootgrp.variables.items():
        if dim1 in ncVar.dimensions and varname not in ['alt', 'lat', 'lon', 'x', 'y']:
            ncVar.setncattr('coordinates', 'lat lon')                           # For CF-compliance
            if pointCF:
                ncVar.setncattr('grid_mapping', grid_mapping)                       # For CF-compliance
        del ncVar, varname

    # Fill in global attributes
    rootgrp.featureType = 'timeSeries'                                          # For compliance
    rootgrp.history = 'Created %s' %time.ctime()

    print('        Starting to fill in routing table NC file.')
    ids[:] = numpy.array(order)                                                             # Fill in id field information
    fromnodes = [From_To[arcid][0] for arcid in order]                                      # The FROM node from the streams shapefile (used later as a key))
    tonodes = [From_To[arcid][1] for arcid in order]                                        # The TO node from the streams shapefile (used later as a key)
    drops = [int(NodeElev[fromnode] or 0)-int(NodeElev[tonode] or 0) for fromnode, tonode in zip(fromnodes, tonodes)]	# Fix issues related to None in NodeElev
    #drops = [NodeElev[fromnode]-NodeElev[tonode] for fromnode, tonode in zip(fromnodes, tonodes)]
    drops = [x if x>0 else 0 for x in drops]                                                # Replace negative values with 0

    # Set variable value arrays
    fromlist = [Arc_To_From[arcid] for arcid in order]                                      # List containes 'None' values, must convert to numpy.nan
    tolist = [Arc_From_To[arcid] for arcid in order]                                        # List containes 'None' values, must convert to numpy.nan

    # Change None values to 0.  Could alternatively use numpy.nan
    froms[:] = numpy.array([0 if x==None else x for x in fromlist])                    # Note that the From in this case is the ARCID of any of the immediately upstream contributing segments
    tos[:] = numpy.array([0 if x==None else x for x in tolist])                        # Note that the To in this case is the ARCID of the immediately downstream segment

    # Fill in other variables
    slons[:] = numpy.array([NodesLL[fromnode][0] for fromnode in fromnodes])
    slats[:] = numpy.array([NodesLL[fromnode][1] for fromnode in fromnodes])
    geo_x[:] = numpy.array([NodesXY[fromnode][0] for fromnode in fromnodes])
    geo_y[:] = numpy.array([NodesXY[fromnode][1] for fromnode in fromnodes])
    selevs[:] = numpy.array([round(NodeElev[fromnode], 3) for fromnode in fromnodes])       # Round to 3 digits
    Lengthsnc[:] = numpy.array([round(Lengths[arcid], 1) for arcid in order])               # Round to 1 digit

    # Modify order and slope arrays
    order_ = [1 if arcid in Straglers else StrOrder[From_To[arcid][0]] for arcid in order]  # Deal with issue of some segments being assigned higher orders than they should.
    orders[:] = numpy.array(order_)
    Sos_ = numpy.round(numpy.array(drops).astype(float)/Lengthsnc[:], 3)        # Must convert list to float to result in floats
    numpy.place(Sos_, Sos_==0, [0.005])                                         # Set minimum slope to be 0.005
    Sos[:] = Sos_[:]

    # Set default arrays
    Qis[:] = Qi
    MusKs[:] = MusK
    MusXs[:] = MusX
    ns[:] = n
    ChSlps[:] = ChSlp
    BtmWdths[:] = BtmWdth
    Times[:] = 0
    Kcs[:] = Kc

    # Added 10/10/2017 by KMS to include user-supplied gages in reach-based routing files
    if gageDict is not None:
        Gages[:,:] = numpy.asarray([tuple(str(gageDict[arcid]).rjust(15)) if arcid in gageDict else tuple('               ') for arcid in order])
    else:
        Gages[:,:] = numpy.asarray([tuple('               ') for arcid in order])    # asarray converts from tuple to array
    del gageDict

    # Close file
    rootgrp.close()
    print('        Done writing NC file to disk.')
    print('    Routing table created without error.')
    return

def Routing_Table(projdir, sr2, grid_obj, channelgrid, fdir, Elev, Strahler, gages=None):
    """If "Create reach-based routing files?" is selected, this function will create
    the Route_Link.nc table and Streams.shp shapefiles in the output directory."""

    ##        # UNUSED
    ##        stream_id = "stream_id.tif"
    ##        stream_length = "stream_length.tif"
    ##        streams_vector = "streams.shp"
    ##        wbt.stream_link_identifier(dir_d8, streams, stream_id, esri_pntr=esri_pntr, zero_background=zero_background)
    ##        wbt.stream_link_length(dir_d8, stream_id, stream_length, esri_pntr=esri_pntr, zero_background=zero_background)
    ##        wbt.raster_streams_to_vector(stream_id, dir_d8, streams_vector, esri_pntr=esri_pntr)

    # Stackless topological sort algorithm, adapted from: http://stackoverflow.com/questions/15038876/topological-sort-python
    def sort_topologically_stackless(graph):

        '''This function will navigate through the list of segments until all are accounted
        for. The result is a sorted list of which stream segments should be listed
        first. Simply provide a topology dictionary {Fromnode:[ToNode,...]} and a sorted list
        is produced that will provide the order for navigating downstream. This version
        is "stackless", meaning it will not hit the recursion limit of 1000.'''

        levels_by_name = {}
        names_by_level = defaultdict(set)

        def add_level_to_name(name, level):
            levels_by_name[name] = level
            names_by_level[level].add(name)

        def walk_depth_first(name):
            stack = [name]
            while(stack):
                name = stack.pop()
                if name in levels_by_name:
                    continue

                if name not in graph or not graph[name]:
                    level = 0
                    add_level_to_name(name, level)
                    continue

                children = graph[name]

                children_not_calculated = [child for child in children if child not in levels_by_name]
                if children_not_calculated:
                    stack.append(name)
                    stack.extend(children_not_calculated)
                    continue

                level = 1 + max(levels_by_name[lname] for lname in children)
                add_level_to_name(name, level)

        for name in graph:
            walk_depth_first(name)

        list1 = list(takewhile(lambda x: x is not None, (names_by_level.get(i, None) for i in count())))
        list2 = [item for sublist in list1 for item in sublist][::-1]               # Added by KMS 9/2/2015 to reverse sort the list
        list3 = [x for x in list2 if x is not None]                                 # Remove None values from list
        return list3

    print('    Routing table will be created...')

    # Get grid information from grid object
    proj = grid_obj.proj
    (xMin, yMin, xMax, yMax) = grid_obj.grid_extent()

    # Set output coordinate system environment
    sr1 = osr.SpatialReference()                                                # Build empty spatial reference object
    sr1.ImportFromWkt(wkt_text)                                                  # Load default sphere lat/lon CRS from global attribute wkt_text

    # Output files
    outStreams = os.path.join(projdir, StreamSHP)
    RoutingNC = os.path.join(projdir, RT_nc)
    OutFC = os.path.join("in_memory", "Nodes")
    OutFC2 = os.path.join("in_memory", "NodeElev")
    OutFC3 = os.path.join("in_memory", "NodeOrder")
    outRaster = os.path.join("in_memory", "LINKID")

    # Build Stream Features shapefile
    StreamToFeature(channelgrid, fdir, outStreams, "NO_SIMPLIFY")
    print('        Stream to features step complete.')

    # Create a raster based on the feature IDs that were created in StreamToFeature
    arcpy.FeatureToRaster_conversion(outStreams, 'ARCID', outRaster, channelgrid)                   # Must do this to get "ARCID" field into the raster
    maxValue = arcpy.SearchCursor(outStreams, "", "", "", 'ARCID' + " D").next().getValue('ARCID')  # Gather highest "ARCID" value from field of segment IDs
    maxRasterValue = outRaster.GetRasterBand(1).GetMaximum()                    # Gather maximum "ARCID" value from raster
    if int(maxRasterValue[0]) > maxValue:
        print('        Setting linkid values of {0} to Null.'.format(maxRasterValue[0]))
        whereClause = "VALUE = {0}".format(int(maxRasterValue[0]))
        outRaster = SetNull(outRaster, outRaster, whereClause)                  # This should eliminate the discrepency between the numbers of features in outStreams and outRaster
    outRaster = Con(IsNull(outRaster) == 1, NoDataVal, outRaster)               # Set Null values to -9999 in LINKID raster

    # Add gage points from input forecast points file
    frxst_linkID = {}                                                           # Create blank dictionary so that it exists and can be deleted later
    if gages is not None:
        print('        Adding forecast points:LINKID association.')

        # Input forecast points raster must be forecast point IDs and NoData only
        out_frxst_linkIDs = os.path.join('in_memory', 'frxst_linkIDs')

        # Sample the LINKID value for each forecast point. Result is a table
        Sample(outRaster, gages, out_frxst_linkIDs, "NEAREST")
        frxst_linkID = {int(row[-1]):int(row[1]) for row in arcpy.da.SearchCursor(out_frxst_linkIDs, '*')}  # Dictionary of LINKID:forecast point for all forecast points

        # Clean up
        arcpy.Delete_management(gages)
        arcpy.Delete_management(out_frxst_linkIDs)
        print('        Found {0} forecast point:LINKID associations.'.format(len(frxst_linkID)))
        del gages, out_frxst_linkIDs

    # Create new Feature Class and begin populating it
    arcpy.CreateFeatureclass_management("in_memory", "Nodes", "POINT")
    arcpy.AddField_management(OutFC, "NODE", "LONG")

    # Initiate dictionaries for storing topology information
    From_To = {}                                                                # From_Node/To_Node information
    Nodes = {}                                                                  # Node firstpoint/lastpoint XY information
    NodesLL = {}                                                                # Stores the projected node Lat/Lon information in EMEP Sphere GCS
    Lengths = {}                                                                # Gather the stream feature length
    StrOrder = {}                                                               # Store stream order for each node

    # Enter for loop for each feature/row to gather length and endpoints of stream segments                                                       # Create an array and point object needed to create features
    point = arcpy.Point()
    with arcpy.da.SearchCursor(outStreams, ['SHAPE@', 'ARCID', 'FROM_NODE', 'TO_NODE']) as rows:                       # Start SearchCursor to look through all linesegments
        for row in rows:
            ID = row[1]                                                         # Get Basin ARCID
            From_To[ID] = [row[2], row[3]]                                      # Store From/To node for each segment
            feat = row[0]                                                       # Create the geometry object 'feat'

            if feat.isMultipart == False:                                       # Make sure that each part is a single part feature
                firstpoint = feat.firstPoint                                    # First point feature geometry
                lastpoint = feat.lastPoint                                      # Last point feature geometry
                Lengths[ID] = feat.length                                       # Store length of the stream segment

                # Gather the X and Y of the top and bottom ends
                for i in firstpoint,lastpoint:                                  # Now put this geometry into new feature class
                    point.X = i.X
                    point.Y = i.Y
                    pointGeometry = arcpy.PointGeometry(point, sr2)
                    projpoint = pointGeometry.projectAs(sr1)                    # Convert to latitude/longitude on the sphere
                    projpoint1 = projpoint.firstPoint
                    if i == firstpoint:                                         # Top Point
                        if row[2] in Nodes:
                            continue                                            # Skip entry if record already exists in dictionary
                        Nodes[row[2]] = (i.X, i.Y)
                        NodesLL[row[2]] = (projpoint1.X, projpoint1.Y)
                    elif i == lastpoint:                                        # Bottom Point
                        if row[3] in Nodes:
                            continue                                            # Skip entry if record already exists in dictionary
                        Nodes[row[3]] = (i.X, i.Y)
                        NodesLL[row[3]] = (projpoint1.X, projpoint1.Y)
            else:
                print('This is a multipart line feature and cannot be handled.')
    #rows.reset()                                                                # Not sure why this is necessary
    del row, rows, point, ID, feat, firstpoint, lastpoint, pointGeometry, projpoint, projpoint1, i, sr2
    print('        Done reading streams layer.')

    # Make a point feature class out of the nodes
    IC = arcpy.da.InsertCursor(OutFC, ['SHAPE@', 'NODE'])
    NodesXY = Nodes                                                             # Copy the Nodes dictionary before it gets modified
    for node in list(Nodes.keys()):                                                   # Now we have to adjust the points that fall outside of the raster edge

        # Adjust X
        if Nodes[node][0] <= xMin:
            Nodes[node] = ((Nodes[node][0] + (grid_obj.ncols/2)), Nodes[node][1])
        elif Nodes[node][0] >= xMax:
            Nodes[node] = ((Nodes[node][0] - (grid_obj.ncols/2)), Nodes[node][1])

        # Adjust Y
        if Nodes[node][1] <= yMin:
            Nodes[node] = (Nodes[node][0], (Nodes[node][1] + (grid_obj.nrows/2)))
        elif Nodes[node][1] >= yMax:
            Nodes[node] = (Nodes[node][0], (Nodes[node][1] - (grid_obj.nrows/2)))

        IC.insertRow([Nodes[node], node])                                       # Insert point and ID information into the point feature class

    del IC, node, Nodes, xMin, yMin, xMax, yMax
    print('        Done building Nodes layer with adjustments.')

    # Get the elevation values for the nodes feature class
    ExtractValuesToPoints(OutFC, Elev, OutFC2, "NONE", "VALUE_ONLY")
    print('        Done extracting elevations to points.')
    NodeElev = {row[0]: row[1] for row in arcpy.da.SearchCursor(OutFC2, ['NODE', 'RASTERVALU'])}
    print('        Done reading node elevations.')
    arcpy.Delete_management(OutFC2)                                             # Clean up

    # Incorporate Strahler Order
    ExtractValuesToPoints(OutFC, Strahler, OutFC3, "NONE", "VALUE_ONLY")
    with arcpy.da.SearchCursor(OutFC3, ['NODE', 'RASTERVALU']) as rows:
        for row in rows:
            if row[1] <= 0:                                                     # Reclass -9999 values to 1
                order = 1
            else:
                order = row[1]
            StrOrder[row[0]] = order
    print('        Done reading Strahler stream orders.')
    arcpy.Delete_management(OutFC)                                              # Clean up
    arcpy.Delete_management(OutFC3)                                             # Clean up

    # Add stream order into the streams shapefile
    arcpy.AddField_management(outStreams, "Order_", "SHORT")                    # Add field for "Order_"
    arcpy.AddField_management(outStreams, "index", "LONG")                      # Add field for "index" that gives the topologically sorted order of streams in the out nc file
    arcpy.AddField_management(outStreams, "GageID", "TEXT", "#", "#", 15, "#", "NULLABLE")  # Add field for gages
    with arcpy.da.UpdateCursor(outStreams, ['ARCID', 'Order_', 'GageID']) as rows:# Start UpdateCursor to add the stream order information
        for row in rows:
            row[1] = StrOrder[From_To[row[0]][0]]                               # This gets the stream order of the upstream node
            if row[0] in frxst_linkID:
                row[2] = frxst_linkID[row[0]]
            rows.updateRow(row)

    # Deconstruct from Node space to segment space
    Arc_From = {x:From_To[x][0] for x in From_To}                                       # Build ARCID-keyed topology of The ARCID:FromNode
    From_Arc = {From_To[x][0]:x for x in From_To}                                       # Build Node-keyed topology of The FromNode:ARCID
    From_To2 = {From_To[x][0]:From_To[x][1] for x in From_To}                           # Build Node-keyed topology of The FromNode:ToNode
    Arc_From_To = {item:From_Arc.get(From_To2[Arc_From[item]]) for item in Arc_From}    # Build ARCID-keyed topology of the ARCID:ToARCID   ".get()" allows None to be placed in dictionary
    To_From = {From_To[x][1]:From_To[x][0] for x in From_To}                            # Build Node-keyed topology of The ToNode:FromNode
    Arc_To_From = {item:From_Arc.get(To_From.get(Arc_From[item])) for item in Arc_From} # Build ARCID-keyed topology of the ARCID:FromARCID. ".get()" allows None to be placed in dictionary

    # Get the order of segments according to a simple topological sort
    whereclause = "%s > 1" %arcpy.AddFieldDelimiters(outStreams, "Order_")
    Straglers = [row[0] for row in arcpy.da.SearchCursor(outStreams, 'ARCID', whereclause) if Arc_To_From.get(row[0]) is None]    # These are not picked up by the other method
    tic2 = time.time()
    order = sort_topologically_stackless({item:[From_Arc.get(From_To2[Arc_From[item]])] for item in Arc_From})    # 'order' variable is a list of LINK IDs that have been reordered according to a simple topological sort
    print('        Time elapsed for sorting: {0: 3.2f} seconds'.format(time.time()-tic2))

    # Fix Streams shapefile from "FROM_NODE" and "TO_NODE" to "FROM_ARCID" and "TO_ARCID"
    arcpy.AddField_management(outStreams, "From_ArcID", "LONG", "#", "#", "#", "#", "NULLABLE")     # Add field for "From_ArcID"
    arcpy.AddField_management(outStreams, "To_ArcID", "LONG", "#", "#", "#", "#", "NULLABLE")       # Add field for "To_ArcID"
    with arcpy.da.UpdateCursor(outStreams, ("ARCID", "From_ArcID", "To_ArcID", "Order_", "index")) as cursor:
        for row in cursor:
            arcid = row[0]
            row[4] = order.index(arcid)                                         # Assign field 'index' with the topologically sorted order (adds a bit of time to the process)
            if arcid in Straglers:
                row[3] = 1                                                      # Deal with issue of some segments being assigned higher orders than they should.
            if Arc_To_From[arcid] is not None:
                row[1] = Arc_To_From.get(arcid)
            if Arc_From_To[arcid] is not None:
                row[2] = Arc_From_To.get(arcid)
            cursor.updateRow(row)
    arcpy.DeleteField_management(outStreams, ['FROM_NODE', 'TO_NODE'])          # Delete node-based fields

    # Call function to build the netCDF parameter table
    loglines2 = build_RouteLink(arcpy, RoutingNC, order, From_To, NodeElev, Arc_To_From, Arc_From_To, NodesLL, NodesXY, Lengths, Straglers, StrOrder, sr1, gageDict=frxst_linkID)
    del frxst_linkID, sr1

    # Return
    outArr = BandReadAsArray(outRaster.GetRasterBand(1))               # Create array from raster
    outRaster = None
    del outRaster
    return outArr

def build_LAKEPARM(LakeNC, min_elevs, areas, max_elevs, OrificEs, cen_lats, cen_lons, WeirE_vals):
    '''
    8/10/2017: This function is designed to build the lake parameter netCDF file.
                Ideally, this will be the only place the produces the file, and
                all functions wishing to write the file will reference this function.
    '''
    tic1 = time.time()
    min_elev_keys = list(min_elevs.keys())                                      # 5/31/2019: Supporting Python3

    # Create Lake parameter file
    print('    Starting to create lake parameter table.')
    print('        Lakes Table: {0} Lakes'.format(len(list(areas.keys()))))

    # Create NetCDF output table
    rootgrp = netCDF4.Dataset(LakeNC, 'w', format=outNCType)

    # Create dimensions and set other attribute information
    dim1 = 'feature_id'
    dim = rootgrp.createDimension(dim1, len(min_elevs))

    # Create coordinate variables
    ids = rootgrp.createVariable('lake_id','i4',(dim1))                         # Variable (32-bit signed integer)
    ids[:] = numpy.array(min_elev_keys)                                         # Variable (32-bit signed integer)

    # Create fixed-length variables
    LkAreas = rootgrp.createVariable('LkArea','f8',(dim1))                      # Variable (64-bit floating point)
    LkMxEs = rootgrp.createVariable('LkMxE', 'f8', (dim1))                      # Variable (64-bit floating point)
    WeirCs = rootgrp.createVariable('WeirC', 'f8', (dim1))                      # Variable (64-bit floating point)
    WeirLs = rootgrp.createVariable('WeirL', 'f8', (dim1))                      # Variable (64-bit floating point)
    OrificeCs = rootgrp.createVariable('OrificeC', 'f8', (dim1))                # Variable (64-bit floating point)
    OrificeAs = rootgrp.createVariable('OrificeA', 'f8', (dim1))                # Variable (64-bit floating point)
    OrificeEs = rootgrp.createVariable('OrificeE', 'f8', (dim1))                # Variable (64-bit floating point)
    lats = rootgrp.createVariable('lat', 'f4', (dim1))                          # Variable (32-bit floating point)
    longs = rootgrp.createVariable('lon', 'f4', (dim1))                         # Variable (32-bit floating point)
    Times = rootgrp.createVariable('time', 'f8', (dim1))                        # Variable (64-bit floating point)
    WeirEs = rootgrp.createVariable('WeirE', 'f8', (dim1))                      # Variable (64-bit floating point)
    AscendOrder = rootgrp.createVariable('ascendingIndex', 'i4', (dim1))        # Variable (32-bit signed integer)
    ifd = rootgrp.createVariable('ifd', 'f4', (dim1))                           # Variable (32-bit floating point)

    # Add CF-compliant coordinate system variable
    if pointCF:
        sr = osr.SpatialReference()                                             # Build empty spatial reference object
        sr.ImportFromProj4(wgs84_proj4)                                    # Imprort from proj4 to avoid EPSG errors (4326)
        projEsri = sr.Clone()
        projEsri.MorphToESRI()                                                      # Alter the projection to Esri's representation of a coordinate system
        PE_string = projEsri.ExportToWkt().replace("'", '"')                        # INVESTIGATE - this somehow may provide better compatability with Esri products?
        grid_mapping = crsVar
        rootgrp = add_CRS_var(rootgrp, sr, 0, grid_mapping, 'latitude_longitude', PE_string)

    # Set variable descriptions
    ids.long_name = 'Lake ID'
    LkAreas.long_name = 'Lake area (sq. km)'
    LkMxEs.long_name = 'Maximum lake elevation (m ASL)'
    WeirCs.long_name = 'Weir coefficient'
    WeirLs.long_name = 'Weir length (m)'
    OrificeCs.long_name = 'Orifice coefficient'
    OrificeAs.long_name = 'Orifice cross-sectional area (sq. m)'
    OrificeEs.long_name = 'Orifice elevation (m ASL)'
    WeirEs.long_name = 'Weir elevation (m ASL)'
    lats.long_name = 'latitude of the lake centroid'
    longs.long_name = 'longitude of the lake centroid'
    AscendOrder.long_name = 'Index to use for sorting IDs (ascending)'
    ifd.long_name = 'Initial fraction water depth'
    longs.units = 'degrees_east'                                                # For compliance
    lats.units = 'degrees_north'                                                # For compliance
    longs.standard_name = 'longitude'                                           # For compliance
    lats.standard_name = 'latitude'                                             # For compliance
    Times.standard_name = 'time'                                                # For compliance
    Times.long_name = 'time of measurement'                                     # For compliance
    Times.units = 'days since 2000-01-01 00:00:00'                              # For compliance. Reference time arbitrary
    WeirEs.units = 'm'
    ids.cf_role = "timeseries_id"                                               # For compliance

    # Apply grid_mapping and coordinates attributes to all variables
    for varname, ncVar in rootgrp.variables.items():
        if dim1 in ncVar.dimensions and varname not in ['alt', 'lat', 'lon', 'x', 'y']:
            ncVar.setncattr('coordinates', 'lat lon')                           # For CF-compliance
            if pointCF:
                ncVar.setncattr('grid_mapping', grid_mapping)                       # For CF-compliance
        del ncVar, varname

    # Fill in global attributes
    rootgrp.featureType = 'timeSeries'                                          # For compliance
    rootgrp.history = 'Created %s' %time.ctime()

    print('        Starting to fill in lake parameter table NC file.')
    AscendOrder[:] = numpy.argsort(ids[:])                                  # Use argsort to give the ascending sort order for IDs. Added by KMS 4/4/2017
    LkAreas[:] = numpy.array([float(areas[lkid])/float(1000000) for lkid in min_elev_keys])  # Divide by 1M for kilometers^2
    LkMxEs[:] = numpy.array([max_elevs[lkid] for lkid in min_elev_keys])
    WeirCs[:] = WeirC
    WeirLs[:] = WeirL
    OrificeCs[:] = OrificeC
    OrificeAs[:] = OrificA
    Times[:] = 0
    OrificeEs[:] = numpy.array([OrificEs[lkid] for lkid in min_elev_keys])   # Orifice elevation is 1/3 between 'min' and max lake elevation.
    lats[:] = numpy.array([cen_lats[lkid] for lkid in min_elev_keys])
    longs[:] = numpy.array([cen_lons[lkid] for lkid in min_elev_keys])
    WeirEs[:] = numpy.array([WeirE_vals[lkid] for lkid in min_elev_keys])    # WierH is 0.9 of the distance between the low elevation and max lake elevation
    ifd[:] = ifd_Val

    # Close file
    rootgrp.close()
    print('        Done writing {0} table to disk.'.format(LK_nc))
    return

def array_to_points(in_arr, dtype, GT, proj, NoDataVal=-9999):
    '''
    Build a point feature class for every grid cell that contains a unique value
    in the input array.

    This function is intended to be used to derive pour points from channel pixels
    such as lake outlets.

    Assumes input is a 2D numpy array. Seems to only work with integer field type
    currently.
    '''

    tic1 = time.time()
    valField = 'VALUE'
    xMin, DX, xskew, yMax, yskew, DY = GT

    # Create in-memory output layer to store projected and/or clipped polygons
    drv = ogr.GetDriverByName('MEMORY')                                         # Other options: 'ESRI Shapefile'
    data_source = drv.CreateDataSource('')                                      # Create the data source. If in-memory, use '' or some other string as the data source name
    outLayer = data_source.CreateLayer('', proj, ogr.wkbPoint)               # Create the layer name. Use '' or some other string as the layer name
    outLayer.CreateField(ogr.FieldDefn(valField, dtype))                         # Add a single field to the new layer
    outlayerDef = outLayer.GetLayerDefn()

    # col, row to x, y   From https://www.perrygeo.com/python-affine-transforms.html
    uniques = numpy.unique(in_arr[in_arr!=NoDataVal])                           # Determine unique values
    for idval in uniques:
        locs = numpy.where(in_arr==idval)
        for j, i in zip(locs[0], locs[1]):
            x = (i * DX) + xMin + float(DX/2)
            y = (j * DY) + yMax + float(DY/2)

            # Build output feature
            outFeature = ogr.Feature(outlayerDef)
            outFeature.SetField(valField, int(idval))                                    # Set pixel value attribute
            wkt = "POINT({0} {1})".format(x, y)                                       # create the WKT for the feature using Python string formatting
            point = ogr.CreateGeometryFromWkt(wkt)                                  # Create the point from the Well Known Txt
            outFeature.SetGeometry(point)                                           # Set the feature geometry using the point
            outLayer.CreateFeature(outFeature)                                            # Create the feature in the layer (shapefile)
            outFeature.Destroy()
            outFeature = point = None                                               # Dereference the feature
    outLayer = None
    return data_source

def project_Polygons(InputVector, outProj, clipGeom=None):
    '''
    This function is intended to project a polygon geometry to a new coordinate
    system. Optionally, the geometries can be clipped to an extent rectangle. If
    this option is chosen, the area will be re-calculated for each polygon. The
    assumption is that the linear units are meters.
    '''
    # (InputVector, outProj, clipGeom) = (in_lakes, proj, geom)
    # import ogr
    tic1 = time.time()

    # Get input vector information
    in_vect = ogr.Open(InputVector)                                             # Read the input vector file
    in_layer = in_vect.GetLayer()                                               # Get the 'layer' object from the data source
    in_proj = in_layer.GetSpatialRef()                                          # Obtain the coordinate reference object.
    inlayerDef = in_layer.GetLayerDefn()                                        # Obtain the layer definition for this layer

    # Check if a coordinate transformation (projection) must be performed
    if not outProj.IsSame(in_proj):
        print('    Input shapefile projection does not match requested output. Transforming.')
        coordTrans = osr.CoordinateTransformation(in_proj, outProj)
        trans = True

    # Create in-memory output layer to store projected and/or clipped polygons
    drv = ogr.GetDriverByName('MEMORY')                                         # Other options: 'ESRI Shapefile'
    data_source = drv.CreateDataSource('')                                      # Create the data source. If in-memory, use '' or some other string as the data source name

    # Add the fields we're interested in
    outLayer = data_source.CreateLayer('', outProj, ogr.wkbPolygon)             # Create the layer name. Use '' or some other string as the layer name

    # Build output vector file identical to input with regard to fields
    outLayer.CreateField(ogr.FieldDefn('AREASQKM', ogr.OFTReal))                # Add a single field to the new layer

    # Copy fields from input vector layer to output
    fieldNames = []                                                             # Build empty list of field names
    for i in range(inlayerDef.GetFieldCount()):
        fieldDef = inlayerDef.GetFieldDefn(i)                                   # Get the field definition for this field
        fieldName =  fieldDef.GetName()                                         # Get the field name for this field
        outLayer.CreateField(ogr.FieldDefn(fieldName, fieldDef.GetType()))      # Create a field in the output that matches the field in the input layer
        fieldNames.append(fieldName)                                            # Add field name to list of field names
        #print('    Added field {0}, dtype = {1}'.format(fieldName, fieldDef.GetType()))
    outlayerDef = outLayer.GetLayerDefn()

    # Read all features in layer
    inFeatCount = in_layer.GetFeatureCount()                                    # Get number of input features
    for feature in in_layer:
        geometry = feature.GetGeometryRef()                                     # Get the geometry object from this feature
        if trans:
            geometry.Transform(coordTrans)                                      # Transform the geometry
        if clipGeom:
            if clipGeom.Intersects(geometry):
                geometry = geometry.Intersection(clipGeom)                      # Clip the geometry if requested
            else:
                continue                                                        # Go to the next feature (do not copy)

        # Create output Feature
        outFeature = ogr.Feature(outlayerDef)                                   # Create new feature
        outFeature.SetGeometry(geometry)                                        # Set output Shapefile's feature geometry

        # Fill in fields. All fields in input will be transferred to output
        outFeature.SetField('AREASQKM', float(geometry.Area()/1000000.0))       # Add an area field to re-calculate area
        for fieldname in fieldNames:
            outFeature.SetField(fieldname, feature.GetField(fieldname))
        outLayer.CreateFeature(outFeature)                                      # Add new feature to output Layer
        feature.Destroy()                                                       # Destroy this feature
        feature = outFeature = geometry = None                                  # Clear memory
    outLayer.ResetReading()
    outFeatCount = outLayer.GetFeatureCount()                                   # Get number of features in output layer
    #outLayer = None                                                             # Clear memory

    print('Number of output polygons: {0} of {1}'.format(outFeatCount, inFeatCount))
    print('Completed reprojection and-or clipping in {0:3.2f} seconds.'.format(time.time()-tic1))
    in_vect = inlayerDef = in_layer = None
    return data_source, outLayer, fieldNames

def raster_to_polygon(in_raster, in_proj, geom_typ=ogr.wkbPolygon):
    '''
    Convert a raster object to a polygon layer.
    '''
    tic1 = time.time()

    # Create temporary polygon vector layer
    ds = ogr.GetDriverByName('MEMORY').CreateDataSource('')
    Layer = ds.CreateLayer('', geom_type=geom_typ, srs=in_proj)   # Use projection from input raster
    Layer.CreateField(ogr.FieldDefn('RASTERVALU', ogr.OFTReal))

    # Get raster band information
    band = in_raster.GetRasterBand(1)                                           # Get raster band 1
    stats = band.ComputeStatistics(0)                                       # Force recomputation of statistics

    # Polygonize the raster and write features to in-memory vector layer
    result = gdal.Polygonize(band, band, Layer, 0, ["8CONNECTED=8"], callback=None)     # With 8-connectedness
    if result != 0:
        print('Polygonize raster failed')
    else:
        print('  Created polygon from input raster in {0: 3.2f} seconds'.format(time.time()-tic1))

    #feature = Layer.GetNextFeature()
    return ds, Layer

def dissolve_polygon_to_multipolygon(inDS, inLayer, fieldname, quiet=True):
    '''
    This function will dissolve the polygons in an input polygon feature layer
    and provide an output in-memory multipolygon layer with the dissolved geometries.
    '''
    tic1 = time.time()
    in_proj = inLayer.GetSpatialRef()

    # Create temporary polygon vector layer
    ds = ogr.GetDriverByName('MEMORY').CreateDataSource('')
    outLayer = ds.CreateLayer('', geom_type=ogr.wkbMultiPolygon, srs=in_proj)   # Use projection from input raster
    inlayerDef = inLayer.GetLayerDefn()                                        # Obtain the layer definition for this layer

    # Copy fields from input vector layer to output
    fieldNames = []                                                             # Build empty list of field names
    for i in range(inlayerDef.GetFieldCount()):
        fieldDef = inlayerDef.GetFieldDefn(i)                                   # Get the field definition for this field
        fieldName =  fieldDef.GetName()                                         # Get the field name for this field
        outLayer.CreateField(ogr.FieldDefn(fieldName, fieldDef.GetType()))      # Create a field in the output that matches the field in the input layer
        fieldNames.append(fieldName)                                            # Add field name to list of field names
    outlayerDef = outLayer.GetLayerDefn()
    inlayerDef = None

    # Set up list of unique lake IDs over which to dissolve singlepart to multiapart polygons
    valuelist = set([feature.GetField(fieldname) for feature in inLayer])       # Get list of unique IDs
    inLayer.ResetReading()                                                      # Reset layer
    for idval in valuelist:
        inLayer.SetAttributeFilter('"%s" = %s' %(fieldname, idval))         # Select the ID from the layer
        polygeom = ogr.Geometry(ogr.wkbMultiPolygon)
        for feature in inLayer:
            polygeom.AddGeometry(feature.GetGeometryRef())
        #polygeom = polygeom.UnionCascaded()
        if not quiet:
            print('  [{0}] Number of features in the original polygon: {1},  multipolygon: {2}'.format(int(idval), inLayer.GetFeatureCount(), polygeom.GetGeometryCount()))

        # Create output Feature
        outFeature = ogr.Feature(outlayerDef)                                   # Create new feature
        outFeature.SetGeometry(polygeom)                                        # Set output Shapefile's feature geometry

        # Fill in fields. All fields in input will be transferred to output
        for fieldname in fieldNames:
            if fieldname == 'AREASQKM':
                outFeature.SetField(fieldname, float(polygeom.Area()/1000000.0))       # Add an area field to re-calculate area
            else:
                outFeature.SetField(fieldname, feature.GetField(fieldname))
        outLayer.CreateFeature(outFeature)                                      # Add new feature to output Layer
        feature = outFeature = polygeom = None                                  # Clear memory
        inLayer.SetAttributeFilter(None)
    inlayerDef = outlayerDef = outLayer = None
    del idval, fieldNames, valuelist, in_proj
    print('    Done dissolving input layer in {0:3.2f} seconds.'.format(time.time()-tic1))
    return ds

def add_reservoirs(rootgrp, projdir, fac, in_lakes, grid_obj, lakeIDfield=None, Gridded=True):
    """
    This function is intended to add reservoirs into the model grid stack, such
    that the channelgrid and lake grids are modified to accomodate reservoirs and
    lakes.

    This version does not attempt to subset the lakes by a size threshold, nor
    does it filter based on FTYPE.

    2/23/2018:
        Change made to how AREA paramter is calculated in LAKEPARM. Previously, it
        was based on the gridded lake area. Now it is based on the AREASQKM field
        in the input shapefile. This change was made because in NWM, the lakes
        are represented as objects, and are not resolved on a grid.

    10/15/2019:
        Adding a GRIDDED flag. If True, a gridded WRF-Hydro run is assumed, and
        no lakes will be added to LAKEPARM.nc which are not resolved on the
        routing grid. If False, all lakes coincident with the domain boundary
        will be included in LAKEPARM.nc.
    """
    #(rootgrp, projdir, fac, in_lakes, grid_obj, lakeIDfield, Gridded) = (rootgrp2, projdir, fac, in_lakes, fine_grid, None, None)
    tic1 = time.time()                                                          # Set timer

    # Setup Whitebox tools
    wbt = WhiteboxTools()
    wbt.verbose = False
    wbt.work_dir = projdir

    # Outputs
    LakeNC = os.path.join(projdir, LK_nc)
    outshp = os.path.join(projdir, 'in_lakes_clip.shp')                         # Clipped input lakes shapefile
    LakeRas = os.path.join(projdir, 'LakeGrid.tif')
    frxst_FC = os.path.join(projdir, 'Lake_outlets.shp')
    out_lake_raster_shp = os.path.join(projdir, "out_lake_raster.shp")
    snapPour = 'Lake_snapped_pour_points.shp'                                   # Pour points snapped downstream of lake outlets

    # Get domain extent for cliping geometry
    geom = grid_obj.boundarySHP('', 'MEMORY')

    # Use extent of the template raster to add a feature layer of lake polygons
    lake_ds, lake_layer, fieldNames = project_Polygons(in_lakes, grid_obj.proj, clipGeom=geom)
    geom = None

    # Assign a new ID field for lakes, numbered 1...n. Add field to store this information if necessary
    if lakeIDfield is None:
        print('    Adding auto-incremented lake ID field (1...n)')
        lakeID = "newID"
        if lakeID not in fieldNames:
            lake_layer.CreateField(ogr.FieldDefn(lakeID, ogr.OFTInteger))
        for num,feature in enumerate(lake_layer):
            feature.SetField(lakeID, num+1)      # Add an area field to re-calculate area
            lake_layer.SetFeature(feature)
        lake_layer.ResetReading()
        feature = None
    else:
        print('    Using provided lake ID field: {0}'.format(lakeIDfield))
        lakeID = lakeIDfield                                                    # Use existing field specified by 'lakeIDfield' parameter

    # Gather areas from AREASQKM field
    areas = {}
    for feature in lake_layer:
        areas[feature.GetField(lakeID)] = feature.GetField('AREASQKM')
        feature = None
    lake_layer.ResetReading()
    lakeIDList = list(areas.keys())

    # Save to disk in order to use in the FeatToRaster function.
    out_ds  = ogr.GetDriverByName(VectorDriver).CopyDataSource(lake_ds, outshp)
    out_ds = None

    # Convert lake geometries to raster geometries on the model grid
    LakeRaster = FeatToRaster(outshp, fac, lakeID, gdal.GDT_Int32, NoData=NoDataVal)
    Lake_arr = BandReadAsArray(LakeRaster.GetRasterBand(1))                     # Read raster object into numpy array
    Lake_arr[Lake_arr==0] = NoDataVal                                           # Convert 0 to WRF-Hydro NoData
    rootgrp.variables['LAKEGRID'][:] = Lake_arr                                # Write array to output netCDF file
    print('    Process: LAKEGRID written to output netCDF.')

    # Find the maximum flow accumulation value for each lake
    lake_uniques = numpy.unique(Lake_arr[Lake_arr!=NoDataVal])
    flac_arr = rootgrp.variables['FLOWACC'][:]                                  # Read flow accumulation array from Fulldom
    flac_max = {lake:flac_arr[Lake_arr==lake].max() for lake in lake_uniques}

    # Iterate over lakes, assigning the outlet pixel to the lake ID in channelgrid
    strm_arr = rootgrp.variables['CHANNELGRID'][:]                              # Read channel grid array from Fulldom
    strm_arr[Lake_arr>0] = NoDataVal                                            # Set all lake areas to WRF-Hydro NoData value under this lake
    for lake,maxfac in flac_max.items():
        strm_arr[numpy.logical_and(Lake_arr==lake, flac_arr==maxfac)] = lake    # Set the lake outlet to the lake ID in Channelgrid
    del flac_arr
    rootgrp.variables['CHANNELGRID'][:] = strm_arr
    print('    Process: CHANNELGRID written to output netCDF.')

    # Now march down a set number of pixels to get minimum lake elevation
    strm_arr[strm_arr<1] = NoDataVal                                            # Remove channels (active and inactive)
    ds = array_to_points(strm_arr, ogr.OFTInteger, grid_obj.GeoTransform(), grid_obj.proj)
    out_ds = ogr.GetDriverByName(VectorDriver).CopyDataSource(ds, frxst_FC)    # Copy to file on disk
    ds = out_ds = None
    del strm_arr, ds, out_ds

    tolerance = grid_obj.DX * LK_walker
    snapPourFile = os.path.join(projdir, snapPour)
    wbt.snap_pour_points(frxst_FC, fac, snapPour, tolerance)                  # Snap pour points to flow accumulation grid within a tolerance

    # Read the shapefile from previous Snap Pour Points and extract the values directly
    fill_arr = rootgrp.variables['TOPOGRAPHY'][:]                               # Read elevation array from Fulldom
    snap_ds = ogr.Open(snapPourFile, 0)
    pointlyr = snap_ds.GetLayer()                                               # Get the 'layer' object from the data source
    min_elevs = {}
    for feature in pointlyr:
        idval = feature.GetField('VALUE')
        point = feature.GetGeometryRef()
        row, col = grid_obj.xy_to_grid_ij(point.GetX(), point.GetY())
        min_elevs[idval] = fill_arr[row, col]
        feature = point = None
        del idval, row, col
    snap_ds = pointlyr = None
    ogr.GetDriverByName(VectorDriver).DeleteDataSource(snapPourFile)

    # Gathering minimum elevation reqiures sampling at the location below reservoir outlets
    max_elevs = {lake:fill_arr[Lake_arr==lake].max() for lake in lake_uniques}
    del Lake_arr, lake_uniques

    # Delete temporary point shapefiles
    ogr.GetDriverByName(VectorDriver).DeleteDataSource(frxst_FC)

    # Only add in 'missing' lakes if this is a reach-routing simulation and lakes
    # don't need to be resolved on the grid.
    if not Gridded:
        # 2/23/2018: Find the missing lakes and sample elevation at their centroid.
        min_elev_keys = list(min_elevs.keys())
        print('    Lakes in minimum elevation dict: {0}'.format(len(min_elev_keys))) # Delete later
        MissingLks = [item for item in lakeIDList if item not in min_elev_keys]     # 2/23/2018: Find lakes that were not resolved on the grid
        if len(MissingLks) > 0:
            print('    Found {0} lakes that could not be resolved on the grid: {1}\n      Sampling elevation from the centroid of these features.'.format(len(MissingLks), str(MissingLks)))
            ds = ogr.Open(outshp, 0)
            Lakeslyr = ds.GetLayer()
            Lakeslyr.SetAttributeFilter('"%s" IN (%s)' %(lakeID, str(MissingLks)[1:-1]))    # Select the missing lakes from the input shapefile
            centroidElev = {}
            for feature in Lakeslyr:
                idval = feature.GetField(lakeID)
                centroid = feature.GetGeometryRef().Centroid()
                row, col = grid_obj.xy_to_grid_ij(centroid.GetX(), centroid.GetY())
                centroidElev[idval] = fill_arr[row, col]
                feature = centroid = None
                del row, col, idval
            Lakeslyr = ds = None

            # Update dictionaries with information on the lakes that were not resolved on the grid
            max_elevs.update(centroidElev)                                      # Add single elevation value as max elevation
            min_elevs.update(centroidElev)                                      # Make these lakes the minimum depth
            del centroidElev
        del fill_arr, lakeIDList, MissingLks

    # Give a minimum active lake depth to all lakes with no elevation variation
    elevRange = {key:max_elevs[key]-val for key,val in min_elevs.items()}   # Get lake depths
    noDepthLks = {key:val for key,val in elevRange.items() if val<minDepth}     # Make a dictionary of these lakes
    if len(noDepthLks) > 0:
        print('    Found {0} lakes with no elevation range. Providing minimum depth of %sm for these lakes.'.format(len(noDepthLks), minDepth))
        min_elevs.update({key:max_elevs[key]-minDepth for key,val in noDepthLks.items() if val==0 }) # Give these lakes a minimum depth
        noDepthFile = os.path.join(projdir, 'Lakes_with_minimum_depth.csv')
        with open(noDepthFile,'w') as f:
            w = csv.writer(f)
            for item in noDepthLks.items():
                w.writerows(noDepthLks.items())
            del noDepthFile
    min_elev_keys = list(min_elevs.keys())
    del elevRange, noDepthLks

    # Calculate the Orifice and Wier heights
    # Orifice elevation is 1/3 between the low elevation and max lake elevation
    OrificEs = {x:(min_elevs[x] + ((max_elevs[x] - min_elevs[x])/3)) for x in min_elev_keys}

    # WierH is 0.9 of the distance between the low elevation and max lake elevation
    WeirE_vals = {x:(min_elevs[x] + ((max_elevs[x] - min_elevs[x])*0.9)) for x in min_elev_keys}
    del min_elev_keys

    #  Gather centroid lat/lons
    ds1, Layer = raster_to_polygon(LakeRaster, grid_obj.proj, geom_typ=ogr.wkbMultiPolygon)
    LakeRaster = None

    # Dissolve multiple features to multipolygon feature layer by field value.
    ds2 = dissolve_polygon_to_multipolygon(ds1, Layer, 'RASTERVALU')
    ds1 = None
    #out_shp = ogr.GetDriverByName(VectorDriver).CopyDataSource(ds2, out_lake_raster_shp)
    #out_shp = None

    # Create a point geometry object from gathered lake centroid points
    print('    Starting to gather lake centroid information.')
    #ds2 = ogr.Open(out_lake_raster_shp, 0)
    Lakeslyr = ds2.GetLayer()
    wgs84_proj = osr.SpatialReference()
    wgs84_proj.ImportFromProj4(wgs84_proj4)
    coordTrans = osr.CoordinateTransformation(grid_obj.proj, wgs84_proj)
    cen_lats = {}
    cen_lons = {}
    for feature in Lakeslyr:
        idval = feature.GetField('RASTERVALU')
        centroid = feature.GetGeometryRef().Centroid()
        x, y = centroid.GetX(), centroid.GetY()
        centroid.Transform(coordTrans)                                      # Transform the geometry
        cen_lats[idval] = centroid.GetY()
        cen_lons[idval] = centroid.GetX()
        del x, y, idval
    feature = centroid = Lakeslyr = None    # ds = None
    del ds2, Lakeslyr
    print('    Done gathering lake centroid information.')

    # Call function to build lake parameter netCDF file
    build_LAKEPARM(LakeNC, min_elevs, areas, max_elevs, OrificEs, cen_lats, cen_lons, WeirE_vals)
    print('    Lake parameter table created without error in {0: 3.2f} seconds.'.format(time.time()-tic1))
    return rootgrp

# --- End Functions --- #

# --- Main Codeblock --- #
if __name__ == '__main__':
    pass