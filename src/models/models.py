from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base
from geoalchemy2 import Geometry
from datetime import datetime

Base = declarative_base()

class WeatherStation(Base):
    __tablename__ = 'weather_stations'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    # GiST index automatically created by GeoAlchemy2
    geom = Column(Geometry('POINT', srid=25829, spatial_index=True))

class WeatherObservation(Base):
    __tablename__ = 'weather_observations'
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey('weather_stations.id'))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    temp = Column(Float)
    rh = Column(Float)
    wind_spd = Column(Float)
    precip = Column(Float)

class MunicipalAOI(Base):
    __tablename__ = 'municipal_aoi'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    geom = Column(Geometry('POLYGON', srid=25829, spatial_index=True))