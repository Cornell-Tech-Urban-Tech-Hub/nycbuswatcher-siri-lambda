from secret_helper import get_secret
import requests
import json
import trio
import datetime as dt
import pandas as pd
from parser_helper import BusObservation
import boto3
from botocore.config import Config
import os

def lambda_handler(event, context):
    
    ################################################################## 
    # configuration
    ################################################################## 

    # aws
    aws_bucket_name="busobservatory"
    aws_region_name="us-east-1"
    
    # system to track
    # store api key in secret api_key_{system_id}
    # e.g. api_key_nyct_mta_bus_siri
    system_id="nyct_mta_bus_siri"
    mta_bustime_api_key = get_secret(f'api_key_{system_id}', aws_region_name)['agency_api_key']

    # endpoints
    url_OBA_routelist = "http://bustime.mta.info/api/where/routes-for-agency/MTA%20NYCT.json?key={}"
    url_SIRI_root="http://bustime.mta.info"
    url_SIRI_suffix="/api/siri/vehicle-monitoring.json?key={}&VehicleMonitoringDetailLevel=calls&LineRef={}"
    

    ################################################################## 
    # get current routes
    ##################################################################   

    # fetch from OBA API

    def get_OBA_routelist():
        url = url_OBA_routelist.format(mta_bustime_api_key)
        try:
            response = requests.get(url, timeout=5)
        except Exception as e:
            pass
        finally:
            routes = response.json()
        return routes
    
    # generate list of SIRI endpoints to fetch
    def get_SIRI_urls():
        SIRI_urls_list = []
        routes=get_OBA_routelist()   
        for route in routes['data']['list']:
            route_id = route['id']

            # entries as tuples vs dicts
            SIRI_urls_list.append(
                (
                    route_id,
                    url_SIRI_suffix.format(mta_bustime_api_key,route_id)
                )
            )
            
        return SIRI_urls_list

    ################################################################## 
    # fetch all routes, asynchronously
    ##################################################################   

    async def grabber(s,a_path,route_id):
        try:
            r = await s.get(path=a_path, retries=2, timeout=10)
            feeds.append({route_id:r})
        except Exception as e:
            print (f'\t{dt.datetime.now()}\tTimeout or too many retries for {route_id}.')

    async def main(url_paths):
        from asks.sessions import Session
        s = Session(url_SIRI_root, connections=25)
        async with trio.open_nursery() as n:
            for (route_id, path) in url_paths:
                n.start_soon(grabber, s, path, route_id )

    feeds = []
    trio.run(main, get_SIRI_urls())

    ################################################################## 
    # parse
    ##################################################################   

    buses=[]   
    for route_report in feeds:
        for route_id,route_data in route_report.items():
            route = route_id.split('_')[1]
            #FIXME: trap this more elegantly
            try:
                route_data=route_data.json()            
                if 'VehicleActivity' in route_data['Siri']['ServiceDelivery']['VehicleMonitoringDelivery'][0]:
                    for monitored_vehicle_journey in route_data['Siri']['ServiceDelivery']['VehicleMonitoringDelivery'][0]['VehicleActivity']:
                        bus = BusObservation(route, monitored_vehicle_journey)
                        buses.append(bus)
                else:
                    pass
            except:
                pass
    positions_df = pd.DataFrame([vars(x) for x in buses])
    positions_df['timestamp'] = positions_df['timestamp'].dt.tz_localize(None)
    
    ################################################################## 
    # dump S3 as parquet
    ##################################################################   
    
    # dump to instance ephemeral storage 
    timestamp = dt.datetime.now().replace(microsecond=0)
    filename=f"{system_id}_{timestamp}.parquet".replace(" ", "_").replace(":", "_")
    positions_df.to_parquet(f"/tmp/{filename}", times='int96')

    # upload to S3
    source_path=f"/tmp/{filename}" 
    remote_path=f"{system_id}/unpartitioned/{filename}"  

    session = boto3.Session(region_name=aws_region_name)
    s3 = session.resource('s3')
    result = s3.Bucket(aws_bucket_name).upload_file(source_path,remote_path)
    
    
     # clean up /tmp
    try:
        os.remove(source_path)
    except:
        pass

    # report back to invoker
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"nycbuswatcher-siri-lambda: found {len(feeds)} route feeds and wrote {len(positions_df)} to S3.",
        }),
    }    
