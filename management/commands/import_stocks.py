# management/commands/import_stocks.py
# Create this file in: your_app/management/commands/import_stocks.py

import csv
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from rooms.models import Room, Stock, SMEStock


class Command(BaseCommand):
    help = 'Import stock data from CSV files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--equity_csv',
            type=str,
            required=True,
            help='Path to normal equity CSV file'
        )
        parser.add_argument(
            '--sme_csv',
            type=str,
            required=True,
            help='Path to SME equity CSV file'
        )
        parser.add_argument(
            '--clear_existing',
            action='store_true',
            help='Clear existing stock data before importing'
        )

    def handle(self, *args, **options):
        if options['clear_existing']:
            Stock.objects.all().delete()
            SMEStock.objects.all().delete()
            self.stdout.write(
                self.style.WARNING('Cleared existing stock data')
            )

        # Import normal equity stocks
        if os.path.exists(options['equity_csv']):
            self.import_stocks(options['equity_csv'], Stock, 'Normal Equity')
        else:
            self.stdout.write(
                self.style.ERROR(f'Equity CSV file not found: {options["equity_csv"]}')
            )

        # Import SME stocks
        if os.path.exists(options['sme_csv']):
            self.import_stocks(options['sme_csv'], SMEStock, 'SME Equity')
        else:
            self.stdout.write(
                self.style.ERROR(f'SME CSV file not found: {options["sme_csv"]}')
            )

    def import_stocks(self, csv_file_path, model_class, stock_type):
        success_count = 0
        error_count = 0
        
        self.stdout.write(f'Starting import of {stock_type} stocks from: {csv_file_path}')
        
        with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
            # Try to detect if file has BOM (Byte Order Mark)
            first_line = csvfile.readline()
            if first_line.startswith('\ufeff'):
                csvfile.seek(3)  # Skip BOM
            else:
                csvfile.seek(0)  # Reset to beginning
            
            reader = csv.DictReader(csvfile)
            
            # Print headers to help with debugging
            self.stdout.write(f'CSV Headers: {reader.fieldnames}')
            
            with transaction.atomic():
                for row_num, row in enumerate(reader, start=1):
                    try:
                        # Clean and prepare data
                        symbol = row.get('Symbol', '').strip()
                        name_of_company = row.get('Name of Company', '').strip()
                        series = row.get('Series', '').strip()
                        date_of_listing = self.parse_date(row.get('Date of Listing', ''))
                        paid_up_value = self.parse_decimal(row.get('Paid Up Value', '0'))
                        isin_number = row.get('ISIN Number', '').strip()
                        face_value = self.parse_decimal(row.get('Face Value', '0'))

                        # Validate required fields
                        if not all([symbol, name_of_company, isin_number]):
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Row {row_num}: Missing required fields - skipping'
                                )
                            )
                            error_count += 1
                            continue

                        # Create or update stock
                        stock, created = model_class.objects.update_or_create(
                            symbol=symbol,
                            defaults={
                                'name_of_company': name_of_company,
                                'series': series,
                                'date_of_listing': date_of_listing,
                                'paid_up_value': paid_up_value,
                                'isin_number': isin_number,
                                'face_value': face_value,
                            }
                        )
                        
                        if created:
                            success_count += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Row {row_num}: Updated existing stock {symbol}'
                                )
                            )

                    except Exception as e:
                        error_count += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f'Row {row_num}: Error processing {row.get("Symbol", "Unknown")}: {str(e)}'
                            )
                        )
                        
        self.stdout.write(
            self.style.SUCCESS(
                f'{stock_type} import completed: {success_count} successful, {error_count} errors'
            )
        )

    def parse_date(self, date_string):
        """Parse date string in various formats"""
        if not date_string or date_string.strip() == '':
            return None
            
        date_string = date_string.strip()
        
        # Common date formats
        date_formats = [
            '%Y-%m-%d',      # 2023-12-31
            '%d-%m-%Y',      # 31-12-2023
            '%d/%m/%Y',      # 31/12/2023
            '%m/%d/%Y',      # 12/31/2023
            '%Y/%m/%d',      # 2023/12/31
            '%d-%b-%Y',      # 31-Dec-2023
            '%d %b %Y',      # 31 Dec 2023
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_string, fmt).date()
            except ValueError:
                continue
                
        self.stdout.write(
            self.style.WARNING(f'Could not parse date: {date_string}')
        )
        return None

    def parse_decimal(self, value_string):
        """Parse decimal string, handling various formats"""
        if not value_string or value_string.strip() == '':
            return Decimal('0.00')
            
        # Remove commas and whitespace
        cleaned_value = str(value_string).replace(',', '').strip()
        
        try:
            return Decimal(cleaned_value)
        except:
            self.stdout.write(
                self.style.WARNING(f'Could not parse decimal: {value_string}')
            )
            return Decimal('0.00')