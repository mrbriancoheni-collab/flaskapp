-- Billboard Ads platform tables

CREATE TABLE IF NOT EXISTS billboard_locations (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(200) NOT NULL,
  address_area VARCHAR(200),
  city VARCHAR(100) NOT NULL,
  state VARCHAR(2) NOT NULL,
  zip VARCHAR(10),
  lat DECIMAL(10,7) NOT NULL,
  lng DECIMAL(10,7) NOT NULL,
  screen_type ENUM('digital_billboard','static_billboard','street_level','transit','wallscape') NOT NULL DEFAULT 'digital_billboard',
  size VARCHAR(30) NOT NULL DEFAULT '14x48',
  faces INT NOT NULL DEFAULT 1,
  facing VARCHAR(10),
  traffic_daily INT NOT NULL DEFAULT 20000,
  impressions_weekly INT NOT NULL DEFAULT 50000,
  cpp DECIMAL(8,4) NOT NULL DEFAULT 1.00,
  plays_per_day INT NOT NULL DEFAULT 480,
  dma VARCHAR(100),
  illuminated TINYINT(1) DEFAULT 1,
  image_placeholder VARCHAR(10),
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS billboard_campaigns (
  id INT PRIMARY KEY AUTO_INCREMENT,
  account_id INT NOT NULL,
  name VARCHAR(200) NOT NULL,
  objective ENUM('awareness','traffic','leads') NOT NULL DEFAULT 'awareness',
  status ENUM('draft','pending_review','active','paused','completed','cancelled') NOT NULL DEFAULT 'draft',
  start_date DATE,
  end_date DATE,
  total_budget DECIMAL(10,2) NOT NULL DEFAULT 0,
  spent DECIMAL(10,2) NOT NULL DEFAULT 0,
  plays_delivered INT NOT NULL DEFAULT 0,
  impressions_delivered INT NOT NULL DEFAULT 0,
  creative_headline VARCHAR(100),
  creative_subtext VARCHAR(200),
  creative_cta VARCHAR(60),
  creative_type ENUM('ai_generated','uploaded') DEFAULT 'ai_generated',
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS billboard_campaign_locations (
  id INT PRIMARY KEY AUTO_INCREMENT,
  campaign_id INT NOT NULL,
  location_id INT NOT NULL,
  plays_per_day INT NOT NULL DEFAULT 480,
  cpp DECIMAL(8,4) NOT NULL,
  campaign_days INT NOT NULL DEFAULT 30,
  estimated_total_plays INT NOT NULL DEFAULT 0,
  estimated_impressions INT NOT NULL DEFAULT 0,
  estimated_cost DECIMAL(10,2) NOT NULL DEFAULT 0,
  FOREIGN KEY (campaign_id) REFERENCES billboard_campaigns(id) ON DELETE CASCADE,
  FOREIGN KEY (location_id) REFERENCES billboard_locations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed screen inventory: ~120 screens across 15 US metros

INSERT IGNORE INTO billboard_locations (name, address_area, city, state, zip, lat, lng, screen_type, size, faces, facing, traffic_daily, impressions_weekly, cpp, plays_per_day, dma, illuminated, image_placeholder) VALUES
-- Phoenix AZ (8 screens)
('I-10 & 7th Ave Digital', 'I-10 Westbound near 7th Ave', 'Phoenix', 'AZ', '85007', 33.4484, -112.0773, 'digital_billboard', '14x48', 2, 'W', 72000, 302400, 2.40, 1152, 'Phoenix-Scottsdale', 1, 'amber'),
('Camelback Rd & 32nd St', 'Camelback Corridor', 'Phoenix', 'AZ', '85018', 33.5093, -111.9939, 'digital_billboard', '10x30', 1, 'E', 44000, 184800, 1.80, 864, 'Phoenix-Scottsdale', 1, 'green'),
('I-17 & Peoria Ave Bulletin', 'I-17 North near Peoria', 'Phoenix', 'AZ', '85029', 33.5810, -112.0969, 'digital_billboard', '14x48', 2, 'N', 68000, 285600, 2.20, 1056, 'Phoenix-Scottsdale', 1, 'blue'),
('Central Ave & McDowell Digital', 'Midtown Phoenix', 'Phoenix', 'AZ', '85004', 33.4680, -112.0738, 'street_level', '8x20', 1, 'N', 18000, 50400, 0.90, 480, 'Phoenix-Scottsdale', 1, 'slate'),
('Grand Ave & Indian School', 'Grand Ave Corridor', 'Phoenix', 'AZ', '85017', 33.4976, -112.1012, 'static_billboard', '14x48', 1, 'E', 29000, 60900, 0.85, 1, 'Phoenix-Scottsdale', 1, 'amber'),
('Thomas Rd & 44th St', 'East Phoenix', 'Phoenix', 'AZ', '85018', 33.4870, -111.9896, 'digital_billboard', '10x30', 1, 'W', 36000, 151200, 1.60, 720, 'Phoenix-Scottsdale', 1, 'green'),
('I-10 & 51st Ave Gateway', 'West Phoenix Gateway', 'Phoenix', 'AZ', '85043', 33.4280, -112.1620, 'digital_billboard', '14x48', 2, 'E', 59000, 247800, 2.10, 1008, 'Phoenix-Scottsdale', 1, 'blue'),
('Van Buren & 24th St Transit', 'Central Phoenix Transit', 'Phoenix', 'AZ', '85008', 33.4489, -112.0220, 'transit', '12x25', 1, 'S', 22000, 61600, 1.10, 528, 'Phoenix-Scottsdale', 1, 'slate'),

-- Dallas TX (8 screens)
('I-635 & Preston Rd Digital', 'LBJ Freeway at Preston', 'Dallas', 'TX', '75240', 32.9290, -96.8020, 'digital_billboard', '14x48', 2, 'W', 78000, 327600, 2.60, 1248, 'Dallas-Ft Worth', 1, 'green'),
('I-35E & Mockingbird Ln', 'Central Dallas', 'Dallas', 'TX', '75204', 32.8360, -96.8060, 'digital_billboard', '14x48', 2, 'N', 65000, 273000, 2.30, 1104, 'Dallas-Ft Worth', 1, 'amber'),
('Greenville Ave & Ross Ave', 'Lower Greenville', 'Dallas', 'TX', '75206', 32.8120, -96.7710, 'street_level', '8x20', 1, 'E', 15000, 42000, 0.80, 360, 'Dallas-Ft Worth', 1, 'blue'),
('US-75 & Park Ln Bulletin', 'Central Expressway North', 'Dallas', 'TX', '75231', 32.8660, -96.7810, 'digital_billboard', '10x30', 1, 'S', 50000, 210000, 1.90, 960, 'Dallas-Ft Worth', 1, 'slate'),
('I-30 & Cockrell Hill Digital', 'West Dallas I-30', 'Dallas', 'TX', '75211', 32.7500, -96.9120, 'digital_billboard', '14x48', 2, 'E', 70000, 294000, 2.50, 1200, 'Dallas-Ft Worth', 1, 'green'),
('Oak Lawn Ave & Cedar Springs', 'Uptown Dallas', 'Dallas', 'TX', '75219', 32.8060, -96.8140, 'digital_billboard', '10x30', 1, 'N', 32000, 134400, 1.70, 816, 'Dallas-Ft Worth', 1, 'amber'),
('I-20 & Duncanville Rd', 'South Dallas', 'Dallas', 'TX', '75237', 32.6820, -96.9010, 'static_billboard', '14x48', 1, 'W', 38000, 79800, 0.90, 1, 'Dallas-Ft Worth', 1, 'blue'),
('Commerce St & Griffin St', 'Downtown Dallas', 'Dallas', 'TX', '75202', 32.7820, -96.8010, 'street_level', '8x20', 1, 'W', 20000, 56000, 1.00, 480, 'Dallas-Ft Worth', 1, 'slate'),

-- Houston TX (9 screens)
('I-610 & Westheimer Digital', 'Galleria Area Loop 610', 'Houston', 'TX', '77056', 29.7430, -95.4650, 'digital_billboard', '14x48', 2, 'N', 80000, 336000, 2.70, 1296, 'Houston', 1, 'green'),
('US-290 & Antoine Dr', 'Northwest Houston', 'Houston', 'TX', '77092', 29.8310, -95.4760, 'digital_billboard', '14x48', 2, 'E', 62000, 260400, 2.20, 1056, 'Houston', 1, 'amber'),
('I-45 & Fuqua St South', 'South Houston Corridor', 'Houston', 'TX', '77034', 29.6410, -95.2320, 'digital_billboard', '14x48', 2, 'N', 55000, 231000, 2.00, 960, 'Houston', 1, 'blue'),
('Richmond Ave & Kirby Dr', 'River Oaks Area', 'Houston', 'TX', '77098', 29.7360, -95.4150, 'street_level', '8x20', 1, 'E', 19000, 53200, 0.95, 456, 'Houston', 1, 'slate'),
('I-10 & Gessner Rd Digital', 'West Houston I-10', 'Houston', 'TX', '77055', 29.7650, -95.5390, 'digital_billboard', '10x30', 1, 'W', 48000, 201600, 1.85, 888, 'Houston', 1, 'green'),
('Main St & Midtown Transit', 'Midtown Houston', 'Houston', 'TX', '77002', 29.7430, -95.3700, 'transit', '12x25', 1, 'N', 25000, 70000, 1.15, 552, 'Houston', 1, 'amber'),
('Hwy 6 & Westheimer', 'West Houston Suburban', 'Houston', 'TX', '77082', 29.7360, -95.6370, 'static_billboard', '14x48', 1, 'E', 41000, 86100, 0.88, 1, 'Houston', 1, 'blue'),
('I-69 & Greens Rd', 'North Houston', 'Houston', 'TX', '77067', 29.9210, -95.4470, 'digital_billboard', '14x48', 2, 'S', 58000, 243600, 2.10, 1008, 'Houston', 1, 'slate'),
('Almeda Rd & Holcombe Blvd', 'South Houston Medical Center', 'Houston', 'TX', '77054', 29.6980, -95.4010, 'digital_billboard', '10x30', 1, 'N', 34000, 142800, 1.60, 768, 'Houston', 1, 'green'),

-- Atlanta GA (8 screens)
('I-285 & Roswell Rd Digital', 'Sandy Springs Perimeter', 'Atlanta', 'GA', '30342', 33.9220, -84.3730, 'digital_billboard', '14x48', 2, 'S', 74000, 310800, 2.50, 1200, 'Atlanta', 1, 'amber'),
('I-75 & Howell Mill Rd', 'Midtown Atlanta', 'Atlanta', 'GA', '30318', 33.7960, -84.4190, 'digital_billboard', '14x48', 2, 'N', 61000, 256200, 2.20, 1056, 'Atlanta', 1, 'green'),
('Peachtree Rd & Buckhead Ave', 'Buckhead Village', 'Atlanta', 'GA', '30305', 33.8450, -84.3620, 'street_level', '8x20', 1, 'S', 17000, 47600, 0.85, 408, 'Atlanta', 1, 'blue'),
('I-20 & Moreland Ave East', 'East Atlanta', 'Atlanta', 'GA', '30316', 33.7390, -84.3520, 'digital_billboard', '10x30', 1, 'E', 44000, 184800, 1.75, 840, 'Atlanta', 1, 'slate'),
('Ponce de Leon Ave & Freedom', 'Midtown East Atlanta', 'Atlanta', 'GA', '30308', 33.7740, -84.3540, 'digital_billboard', '10x30', 1, 'W', 29000, 121800, 1.50, 720, 'Atlanta', 1, 'amber'),
('I-85 & Chamblee Tucker Digital', 'Northeast Atlanta', 'Atlanta', 'GA', '30341', 33.8810, -84.2900, 'digital_billboard', '14x48', 2, 'S', 66000, 277200, 2.30, 1104, 'Atlanta', 1, 'green'),
('Camp Creek Pkwy & I-285', 'West Atlanta', 'Atlanta', 'GA', '30331', 33.7230, -84.5490, 'static_billboard', '14x48', 1, 'N', 35000, 73500, 0.82, 1, 'Atlanta', 1, 'blue'),
('Spring St & 14th St Transit', 'Downtown Atlanta', 'Atlanta', 'GA', '30309', 33.7850, -84.3870, 'transit', '12x25', 1, 'E', 23000, 64400, 1.05, 504, 'Atlanta', 1, 'slate'),

-- Denver CO (7 screens)
('I-25 & Colorado Blvd Digital', 'Central Denver I-25', 'Denver', 'CO', '80210', 39.7050, -104.9550, 'digital_billboard', '14x48', 2, 'N', 69000, 289800, 2.40, 1152, 'Denver', 1, 'green'),
('I-70 & Havana St East', 'East Denver Gateway', 'Denver', 'CO', '80239', 39.7490, -104.8370, 'digital_billboard', '14x48', 2, 'W', 57000, 239400, 2.10, 1008, 'Denver', 1, 'amber'),
('Colfax Ave & Broadway', 'Capitol Hill Denver', 'Denver', 'CO', '80203', 39.7400, -104.9880, 'street_level', '8x20', 1, 'E', 21000, 58800, 0.90, 432, 'Denver', 1, 'blue'),
('I-225 & Parker Rd', 'Southeast Denver', 'Denver', 'CO', '80014', 39.6760, -104.8470, 'digital_billboard', '10x30', 1, 'N', 43000, 180600, 1.80, 864, 'Denver', 1, 'slate'),
('Federal Blvd & Alameda Ave', 'West Denver', 'Denver', 'CO', '80219', 39.7140, -105.0380, 'digital_billboard', '10x30', 1, 'S', 31000, 130200, 1.55, 744, 'Denver', 1, 'green'),
('Speer Blvd & 17th Ave', 'Lower Downtown Denver', 'Denver', 'CO', '80202', 39.7390, -105.0010, 'transit', '12x25', 1, 'W', 27000, 75600, 1.20, 576, 'Denver', 1, 'amber'),
('US-36 & Sheridan Blvd', 'North Denver', 'Denver', 'CO', '80003', 39.8370, -105.0580, 'static_billboard', '14x48', 1, 'E', 33000, 69300, 0.80, 1, 'Denver', 1, 'blue'),

-- Orlando FL (7 screens)
('I-4 & International Dr Digital', 'Tourist Corridor I-4', 'Orlando', 'FL', '32819', 28.4420, -81.4710, 'digital_billboard', '14x48', 2, 'W', 76000, 319200, 2.60, 1248, 'Orlando-Daytona', 1, 'green'),
('OBT & Sand Lake Rd', 'Orange Blossom Trail', 'Orlando', 'FL', '32809', 28.4600, -81.4000, 'digital_billboard', '10x30', 1, 'N', 39000, 163800, 1.70, 816, 'Orlando-Daytona', 1, 'amber'),
('I-4 & Lee Rd North', 'North Orlando I-4', 'Orlando', 'FL', '32810', 28.5890, -81.4040, 'digital_billboard', '14x48', 2, 'N', 60000, 252000, 2.20, 1056, 'Orlando-Daytona', 1, 'blue'),
('Colonial Dr & Semoran Blvd', 'East Orlando', 'Orlando', 'FL', '32807', 28.5370, -81.3200, 'street_level', '8x20', 1, 'E', 18000, 50400, 0.88, 432, 'Orlando-Daytona', 1, 'slate'),
('SR-408 & Goldenrod Rd', 'Southeast Orlando', 'Orlando', 'FL', '32822', 28.5110, -81.2850, 'digital_billboard', '10x30', 1, 'S', 41000, 172200, 1.75, 840, 'Orlando-Daytona', 1, 'green'),
('Kirkman Rd & Conroy Rd', 'West Orlando', 'Orlando', 'FL', '32811', 28.4870, -81.4520, 'static_billboard', '14x48', 1, 'W', 28000, 58800, 0.78, 1, 'Orlando-Daytona', 1, 'amber'),
('Downtown Church St Digital', 'Downtown Orlando', 'Orlando', 'FL', '32801', 28.5383, -81.3792, 'transit', '12x25', 1, 'N', 24000, 67200, 1.10, 528, 'Orlando-Daytona', 1, 'blue'),

-- Tampa FL (7 screens)
('I-275 & Dale Mabry Hwy', 'Central Tampa I-275', 'Tampa', 'FL', '33609', 27.9400, -82.5020, 'digital_billboard', '14x48', 2, 'S', 67000, 281400, 2.35, 1128, 'Tampa-St Pete', 1, 'green'),
('Fletcher Ave & Nebraska Ave', 'North Tampa', 'Tampa', 'FL', '33612', 28.0540, -82.4580, 'digital_billboard', '10x30', 1, 'W', 38000, 159600, 1.65, 792, 'Tampa-St Pete', 1, 'amber'),
('US-41 & Hillsborough Ave', 'West Tampa', 'Tampa', 'FL', '33603', 27.9700, -82.4800, 'street_level', '8x20', 1, 'N', 16000, 44800, 0.82, 384, 'Tampa-St Pete', 1, 'blue'),
('I-4 & Brandon Blvd East', 'East Tampa Brandon', 'Tampa', 'FL', '33511', 27.9270, -82.3000, 'digital_billboard', '14x48', 2, 'W', 54000, 226800, 2.00, 960, 'Tampa-St Pete', 1, 'slate'),
('Westshore Blvd & Kennedy Blvd', 'Westshore Business District', 'Tampa', 'FL', '33607', 27.9540, -82.5280, 'digital_billboard', '10x30', 1, 'S', 44000, 184800, 1.80, 864, 'Tampa-St Pete', 1, 'green'),
('Busch Blvd & 56th St', 'Northeast Tampa', 'Tampa', 'FL', '33617', 28.0100, -82.4000, 'static_billboard', '14x48', 1, 'E', 30000, 63000, 0.75, 1, 'Tampa-St Pete', 1, 'amber'),
('Franklin St & Tampa St Transit', 'Downtown Tampa', 'Tampa', 'FL', '33602', 27.9478, -82.4584, 'transit', '12x25', 1, 'W', 22000, 61600, 1.05, 504, 'Tampa-St Pete', 1, 'blue'),

-- Charlotte NC (7 screens)
('I-77 & Tyvola Rd Digital', 'South Charlotte I-77', 'Charlotte', 'NC', '28217', 35.1410, -80.9010, 'digital_billboard', '14x48', 2, 'N', 61000, 256200, 2.20, 1056, 'Charlotte', 1, 'slate'),
('I-85 & Billy Graham Pkwy', 'West Charlotte I-85', 'Charlotte', 'NC', '28208', 35.1890, -80.9420, 'digital_billboard', '14x48', 2, 'E', 55000, 231000, 2.00, 960, 'Charlotte', 1, 'green'),
('Providence Rd & Sharon Rd', 'South Park Area', 'Charlotte', 'NC', '28211', 35.1320, -80.8220, 'street_level', '8x20', 1, 'N', 14000, 39200, 0.78, 336, 'Charlotte', 1, 'amber'),
('N Tryon St & 36th St', 'NoDa Charlotte', 'Charlotte', 'NC', '28206', 35.2340, -80.8300, 'digital_billboard', '10x30', 1, 'S', 32000, 134400, 1.55, 744, 'Charlotte', 1, 'blue'),
('Freedom Dr & Wilkinson Blvd', 'West Charlotte', 'Charlotte', 'NC', '28208', 35.2130, -80.9080, 'static_billboard', '14x48', 1, 'E', 27000, 56700, 0.72, 1, 'Charlotte', 1, 'slate'),
('I-485 & Rea Rd', 'Southeast Charlotte', 'Charlotte', 'NC', '28277', 35.0570, -80.8180, 'digital_billboard', '10x30', 1, 'W', 40000, 168000, 1.70, 816, 'Charlotte', 1, 'green'),
('Trade St & College St Digital', 'Uptown Charlotte', 'Charlotte', 'NC', '28202', 35.2270, -80.8400, 'transit', '12x25', 1, 'N', 20000, 56000, 1.00, 480, 'Charlotte', 1, 'amber'),

-- Nashville TN (7 screens)
('I-65 & Murfreesboro Pike', 'South Nashville I-65', 'Nashville', 'TN', '37211', 36.0760, -86.7490, 'digital_billboard', '14x48', 2, 'N', 58000, 243600, 2.10, 1008, 'Nashville', 1, 'green'),
('I-24 & Nolensville Pike', 'Southeast Nashville', 'Nashville', 'TN', '37211', 36.0860, -86.7040, 'digital_billboard', '14x48', 2, 'W', 51000, 214200, 1.95, 936, 'Nashville', 1, 'blue'),
('Charlotte Pike & White Bridge', 'West Nashville', 'Nashville', 'TN', '37209', 36.1480, -86.8540, 'street_level', '8x20', 1, 'E', 15000, 42000, 0.80, 360, 'Nashville', 1, 'amber'),
('Gallatin Pike & Trinity Ln', 'East Nashville', 'Nashville', 'TN', '37206', 36.1990, -86.7390, 'digital_billboard', '10x30', 1, 'S', 28000, 117600, 1.50, 720, 'Nashville', 1, 'slate'),
('Briley Pkwy & Dickerson Pike', 'Northeast Nashville', 'Nashville', 'TN', '37207', 36.2170, -86.7700, 'digital_billboard', '10x30', 1, 'W', 35000, 147000, 1.60, 768, 'Nashville', 1, 'green'),
('Broadway & 5th Ave Downtown', 'Downtown Nashville', 'Nashville', 'TN', '37203', 36.1612, -86.7785, 'transit', '12x25', 1, 'N', 32000, 89600, 1.25, 600, 'Nashville', 1, 'blue'),
('Harding Pike & White Bridge', 'Belle Meade Corridor', 'Nashville', 'TN', '37205', 36.1310, -86.8690, 'static_billboard', '14x48', 1, 'E', 23000, 48300, 0.70, 1, 'Nashville', 1, 'amber'),

-- Las Vegas NV (7 screens)
('I-15 & Flamingo Rd Digital', 'Las Vegas Strip Corridor', 'Las Vegas', 'NV', '89103', 36.1050, -115.1740, 'digital_billboard', '14x48', 2, 'N', 82000, 344400, 2.80, 1344, 'Las Vegas', 1, 'amber'),
('Boulder Hwy & Flamingo Rd', 'East Las Vegas', 'Las Vegas', 'NV', '89121', 36.1050, -115.0640, 'digital_billboard', '10x30', 1, 'W', 36000, 151200, 1.60, 768, 'Las Vegas', 1, 'green'),
('Sahara Ave & Rainbow Blvd', 'West Las Vegas', 'Las Vegas', 'NV', '89117', 36.1550, -115.2340, 'digital_billboard', '14x48', 2, 'E', 48000, 201600, 1.90, 912, 'Las Vegas', 1, 'blue'),
('Craig Rd & I-15 North', 'North Las Vegas', 'Las Vegas', 'NV', '89030', 36.2420, -115.1660, 'digital_billboard', '14x48', 2, 'S', 55000, 231000, 2.05, 984, 'Las Vegas', 1, 'slate'),
('Charleston Blvd & Decatur', 'Central Las Vegas', 'Las Vegas', 'NV', '89102', 36.1540, -115.2000, 'street_level', '8x20', 1, 'N', 19000, 53200, 0.90, 432, 'Las Vegas', 1, 'amber'),
('Tropicana Ave & Pecos Rd', 'Henderson Area', 'Las Vegas', 'NV', '89121', 36.0820, -115.0580, 'static_billboard', '14x48', 1, 'W', 32000, 67200, 0.85, 1, 'Las Vegas', 1, 'green'),
('Downtown Fremont St Digital', 'Fremont Street Experience', 'Las Vegas', 'NV', '89101', 36.1699, -115.1398, 'transit', '12x25', 1, 'E', 28000, 78400, 1.30, 624, 'Las Vegas', 1, 'blue'),

-- San Antonio TX (7 screens)
('I-10 & Wurzbach Rd', 'Northwest San Antonio', 'San Antonio', 'TX', '78230', 29.5410, -98.5750, 'digital_billboard', '14x48', 2, 'W', 60000, 252000, 2.15, 1032, 'San Antonio', 1, 'slate'),
('US-281 & Stone Oak Pkwy', 'North San Antonio', 'San Antonio', 'TX', '78258', 29.6610, -98.4710, 'digital_billboard', '14x48', 2, 'S', 52000, 218400, 2.00, 960, 'San Antonio', 1, 'green'),
('I-35 & Rittiman Rd', 'Northeast San Antonio', 'San Antonio', 'TX', '78218', 29.5230, -98.4160, 'digital_billboard', '10x30', 1, 'N', 44000, 184800, 1.75, 840, 'San Antonio', 1, 'amber'),
('Military Dr & Pleasanton Rd', 'South San Antonio', 'San Antonio', 'TX', '78221', 29.3700, -98.4910, 'street_level', '8x20', 1, 'E', 13000, 36400, 0.75, 312, 'San Antonio', 1, 'blue'),
('Loop 410 & Culebra Rd', 'West San Antonio', 'San Antonio', 'TX', '78228', 29.4650, -98.5820, 'digital_billboard', '10x30', 1, 'S', 38000, 159600, 1.60, 768, 'San Antonio', 1, 'slate'),
('Alamo Plaza & Commerce St', 'Downtown San Antonio', 'San Antonio', 'TX', '78205', 29.4241, -98.4936, 'transit', '12x25', 1, 'W', 26000, 72800, 1.15, 552, 'San Antonio', 1, 'green'),
('I-37 & Southcross Blvd', 'South Expressway', 'San Antonio', 'TX', '78223', 29.3960, -98.4720, 'static_billboard', '14x48', 1, 'N', 29000, 60900, 0.72, 1, 'San Antonio', 1, 'amber'),

-- Austin TX (7 screens)
('I-35 & 51st St Digital', 'Central Austin I-35', 'Austin', 'TX', '78751', 30.3080, -97.7250, 'digital_billboard', '14x48', 2, 'N', 65000, 273000, 2.35, 1128, 'Austin', 1, 'blue'),
('183 & Burnet Rd', 'North Austin Research Blvd', 'Austin', 'TX', '78758', 30.3760, -97.7230, 'digital_billboard', '14x48', 2, 'W', 56000, 235200, 2.10, 1008, 'Austin', 1, 'green'),
('South Congress & Ben White', 'South Austin SoCo', 'Austin', 'TX', '78704', 30.2340, -97.7510, 'digital_billboard', '10x30', 1, 'N', 34000, 142800, 1.65, 792, 'Austin', 1, 'amber'),
('7th St & Lamar Blvd', 'Central East Austin', 'Austin', 'TX', '78702', 30.2680, -97.7490, 'street_level', '8x20', 1, 'S', 16000, 44800, 0.82, 384, 'Austin', 1, 'blue'),
('US-290 & Oak Hill', 'Southwest Austin', 'Austin', 'TX', '78749', 30.2170, -97.8470, 'digital_billboard', '10x30', 1, 'E', 37000, 155400, 1.60, 768, 'Austin', 1, 'slate'),
('Airport Blvd & 183 Digital', 'East Austin Airport Area', 'Austin', 'TX', '78702', 30.2900, -97.6940, 'digital_billboard', '14x48', 2, 'W', 48000, 201600, 1.90, 912, 'Austin', 1, 'green'),
('Congress Ave & 2nd St Transit', 'Downtown Austin', 'Austin', 'TX', '78701', 30.2672, -97.7431, 'transit', '12x25', 1, 'N', 24000, 67200, 1.10, 528, 'Austin', 1, 'amber'),

-- Jacksonville FL (7 screens)
('I-95 & Baymeadows Rd', 'South Jacksonville', 'Jacksonville', 'FL', '32256', 30.2290, -81.5750, 'digital_billboard', '14x48', 2, 'N', 57000, 239400, 2.05, 984, 'Jacksonville', 1, 'blue'),
('I-10 & Cassat Ave', 'West Jacksonville', 'Jacksonville', 'FL', '32210', 30.3010, -81.7490, 'digital_billboard', '14x48', 2, 'E', 50000, 210000, 1.90, 912, 'Jacksonville', 1, 'slate'),
('Beach Blvd & University Blvd', 'Southeast Jacksonville', 'Jacksonville', 'FL', '32216', 30.2810, -81.5340, 'digital_billboard', '10x30', 1, 'W', 36000, 151200, 1.60, 768, 'Jacksonville', 1, 'green'),
('Normandy Blvd & Blanding Blvd', 'West Side Jacksonville', 'Jacksonville', 'FL', '32210', 30.2680, -81.7290, 'street_level', '8x20', 1, 'N', 13000, 36400, 0.75, 312, 'Jacksonville', 1, 'amber'),
('Dunn Ave & I-95 North', 'North Jacksonville', 'Jacksonville', 'FL', '32218', 30.4030, -81.6450, 'digital_billboard', '10x30', 1, 'S', 32000, 134400, 1.55, 744, 'Jacksonville', 1, 'blue'),
('Hwy 1 & Regency Square', 'East Jacksonville', 'Jacksonville', 'FL', '32225', 30.3130, -81.5080, 'static_billboard', '14x48', 1, 'W', 25000, 52500, 0.70, 1, 'Jacksonville', 1, 'slate'),
('Bay St & Main St Transit', 'Downtown Jacksonville', 'Jacksonville', 'FL', '32202', 30.3315, -81.6553, 'transit', '12x25', 1, 'E', 19000, 53200, 1.00, 480, 'Jacksonville', 1, 'green'),

-- Raleigh NC (6 screens)
('I-40 & Wade Ave Digital', 'West Raleigh I-40', 'Raleigh', 'NC', '27605', 35.7920, -78.7030, 'digital_billboard', '14x48', 2, 'E', 54000, 226800, 2.00, 960, 'Raleigh-Durham', 1, 'amber'),
('Capital Blvd & I-540', 'North Raleigh', 'Raleigh', 'NC', '27616', 35.8740, -78.6260, 'digital_billboard', '14x48', 2, 'S', 48000, 201600, 1.85, 888, 'Raleigh-Durham', 1, 'green'),
('Glenwood Ave & I-440 Beltline', 'North Hills Raleigh', 'Raleigh', 'NC', '27612', 35.8390, -78.6960, 'digital_billboard', '10x30', 1, 'W', 38000, 159600, 1.65, 792, 'Raleigh-Durham', 1, 'blue'),
('Fayetteville St & Martin St', 'Downtown Raleigh', 'Raleigh', 'NC', '27601', 35.7796, -78.6382, 'street_level', '8x20', 1, 'N', 14000, 39200, 0.80, 336, 'Raleigh-Durham', 1, 'slate'),
('Western Blvd & I-440', 'Southwest Raleigh', 'Raleigh', 'NC', '27606', 35.7640, -78.7170, 'digital_billboard', '10x30', 1, 'E', 29000, 121800, 1.50, 720, 'Raleigh-Durham', 1, 'amber'),
('New Bern Ave & Rock Quarry', 'East Raleigh', 'Raleigh', 'NC', '27610', 35.7730, -78.5890, 'static_billboard', '14x48', 1, 'W', 21000, 44100, 0.68, 1, 'Raleigh-Durham', 1, 'green'),

-- Oklahoma City OK (6 screens)
('I-40 & Meridian Ave Digital', 'West OKC I-40', 'Oklahoma City', 'OK', '73108', 35.4610, -97.5720, 'digital_billboard', '14x48', 2, 'E', 56000, 235200, 2.00, 960, 'Oklahoma City', 1, 'blue'),
('I-35 & SE 59th St', 'South OKC', 'Oklahoma City', 'OK', '73129', 35.4010, -97.4790, 'digital_billboard', '14x48', 2, 'N', 44000, 184800, 1.80, 864, 'Oklahoma City', 1, 'slate'),
('Classen Blvd & NW 23rd St', 'Midtown OKC', 'Oklahoma City', 'OK', '73106', 35.4830, -97.5280, 'digital_billboard', '10x30', 1, 'S', 28000, 117600, 1.45, 696, 'Oklahoma City', 1, 'green'),
('Penn & Memorial Rd', 'North OKC Suburban', 'Oklahoma City', 'OK', '73120', 35.5820, -97.5490, 'street_level', '8x20', 1, 'E', 12000, 33600, 0.72, 288, 'Oklahoma City', 'OK', 'amber'),
('I-44 & Portland Ave', 'Northwest OKC', 'Oklahoma City', 'OK', '73112', 35.5000, -97.5720, 'digital_billboard', '10x30', 1, 'W', 36000, 151200, 1.60, 768, 'Oklahoma City', 1, 'blue'),
('Broadway & Park Ave Transit', 'Downtown OKC', 'Oklahoma City', 'OK', '73102', 35.4676, -97.5164, 'transit', '12x25', 1, 'N', 18000, 50400, 1.00, 480, 'Oklahoma City', 1, 'slate');
