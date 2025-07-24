import os
import re
import logging
import pandas as pd
import azure.functions as func

from io import BytesIO
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError

connection_string = os.environ['AzureWebJobsStorage']
blob_service_client = BlobServiceClient.from_connection_string(connection_string)

class Data_Integration:
    def __init__():
        pass
    
    def get_file(blob_service_client: BlobServiceClient, container_name: str, blob_name: str):
        try:
            blob_client = blob_service_client.get_blob_client(container = container_name, blob = blob_name)
            downloader = blob_client.download_blob(encoding='UTF-8-sig')
            blob_text = downloader.readall()
            if re.search(r'\.csv$', blob_name):
                blob_list = [re.split(r',(?=\S)', x) for x in blob_text.replace('\r', '').replace('"', '').split('\n')]
            else:
                blob_list = [re.split(r'\t(?=\S)', x) for x in blob_text.replace('\r', '').replace('"', '').split('\n')]
            df = pd.DataFrame(blob_list[1:], columns = blob_list[0])
            df = df[df.nunique(axis=1) > 1]

            return df 
        
        except Exception as e:
            print(e.message)
    
    
    def load_file(blob_service_client: BlobServiceClient, df: pd.DataFrame, destination_container: str, filename: str):
        try:
            container_client = blob_service_client.create_container(name = destination_container)
        except ResourceExistsError:
            print('A container with this name already exists')
            
        try:
            blob_client = blob_service_client.get_blob_client(container = destination_container, blob = filename)
            output_stream = BytesIO()
            df.to_csv (output_stream, index=False)
            output_stream.seek(0)
            blob_client.upload_blob(output_stream, overwrite=True)
    
            print(f"Blob {filename} has been uploaded to {destination_container} container")
            
        except Exception as e:
            print(e.message)


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
@app.route(route="testing_table")
def testing_table(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        dim_date = Data_Integration.get_file(blob_service_client, 'utilities', 'dim_date.csv')
        dim_country = Data_Integration.get_file(blob_service_client, 'utilities', 'country_lookup.csv')
        testing = Data_Integration.get_file(blob_service_client, 'raw', 'testing/testing.csv')

        dim_date['year_week'] = dim_date['year'].astype(str)\
                            +'-W'\
                            +dim_date['week_of_year'].astype(str).str.pad(width=2, side='left', fillchar='0')
        
        dim_date = dim_date[['date', 'year_week']]
        dim_country = dim_country[['country_code_3_digit', 'country_code_2_digit']]

        dim_date['week_end_date'] = dim_date.groupby('year_week')['date'].transform('max')
        dim_date['week_start_date'] = dim_date.groupby('year_week')['date'].transform('min')
    
        dim_date.drop(columns='date', inplace= True)
        dim_date.drop_duplicates(inplace= True)

        df = pd.merge(testing, dim_date, how='inner', on= 'year_week')
        df = pd.merge(df, dim_country, how= 'inner', left_on= 'country_code', right_on= 'country_code_2_digit')

        df.drop(columns='country_code', inplace= True)

        Data_Integration.load_file(blob_service_client, df, destination_container='processed', filename='testing/testing.csv')

        return func.HttpResponse(f"This HTTP triggered function executed successfully.")
    
    except:
        return func.HttpResponse(
             "This HTTP triggered function does not executed successfully."
                 )

  
@app.route(route="population_table")
def population_table(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        population = Data_Integration.get_file(blob_service_client, 'raw', 'population_by_age/population_by_age.tsv')
        dim_country = Data_Integration.get_file(blob_service_client, 'utilities', 'country_lookup.csv')

        population.columns = population.columns.str.strip()
        population[['age_group','country_code']]  = population['indic_de,geo\\time'].replace(regex = r'^PC_', value='').str.rsplit(',', expand = True)
        population = population[['age_group','country_code', '2019']]
        population.rename(columns = {'2019': 'percentage_2019'}, inplace = True)
        population = population[population['country_code'].apply(lambda x: len(x) == 2)]
        population['percentage_2019'] = pd.to_numeric(population['percentage_2019'].replace(regex = r'[^0-9.]', value=''), errors='coerce')
        population = population.pivot(columns = 'age_group', index = 'country_code', values = 'percentage_2019').sort_values('country_code')
        population.columns = [re.sub(r'^Y','age_group_', col).lower() for col in population.columns.values]
        population.reset_index(inplace = True)

        df = pd.merge(population, dim_country, how = 'inner', left_on = 'country_code', right_on = 'country_code_2_digit')
        df = df[['country', 'country_code_2_digit', 'country_code_3_digit', 'population', 'age_group_0_14', 'age_group_15_24', 'age_group_25_49', 'age_group_50_64', 'age_group_65_79', 'age_group_80_max']]

        Data_Integration.load_file(blob_service_client, df, destination_container='processed', filename='population/population.csv')

        return func.HttpResponse(f"This HTTP triggered function executed successfully.")
    
    except:
        return func.HttpResponse(
             "This HTTP triggered function does not executed successfully."
                 )
