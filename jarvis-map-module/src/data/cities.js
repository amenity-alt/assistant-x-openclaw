/**
 * 全球城市节点：type 说明
 *  hub  — 服务/AI Agent 枢纽（青色）
 *  node — 普通节点（淡蓝）
 *  hot  — 热点区域（黄/橙光晕，风险或高流量）
 */
export const CITIES = [
  // 亚洲（中心区）
  { name: 'Shanghai', lat: 31.23, lon: 121.47, type: 'hub' },
  { name: 'Beijing', lat: 39.9, lon: 116.4, type: 'hub' },
  { name: 'Shenzhen', lat: 22.54, lon: 114.06, type: 'hot' },
  { name: 'Hong Kong', lat: 22.32, lon: 114.17, type: 'hot' },
  { name: 'Tokyo', lat: 35.68, lon: 139.69, type: 'hub' },
  { name: 'Seoul', lat: 37.57, lon: 126.98, type: 'node' },
  { name: 'Singapore', lat: 1.35, lon: 103.82, type: 'hot' },
  { name: 'Mumbai', lat: 19.08, lon: 72.88, type: 'hot' },
  { name: 'Bengaluru', lat: 12.97, lon: 77.59, type: 'node' },
  { name: 'Dubai', lat: 25.2, lon: 55.27, type: 'hub' },
  { name: 'Bangkok', lat: 13.76, lon: 100.5, type: 'node' },
  { name: 'Jakarta', lat: -6.21, lon: 106.85, type: 'node' },
  { name: 'Manila', lat: 14.6, lon: 120.98, type: 'node' },
  { name: 'Taipei', lat: 25.03, lon: 121.57, type: 'node' },
  { name: 'Sydney', lat: -33.87, lon: 151.21, type: 'hub' },
  { name: 'Melbourne', lat: -37.81, lon: 144.96, type: 'node' },
  { name: 'Auckland', lat: -36.85, lon: 174.76, type: 'node' },
  // 欧洲
  { name: 'London', lat: 51.51, lon: -0.13, type: 'hub' },
  { name: 'Frankfurt', lat: 50.11, lon: 8.68, type: 'hub' },
  { name: 'Paris', lat: 48.86, lon: 2.35, type: 'node' },
  { name: 'Berlin', lat: 52.52, lon: 13.4, type: 'node' },
  { name: 'Moscow', lat: 55.76, lon: 37.62, type: 'hot' },
  { name: 'Madrid', lat: 40.42, lon: -3.7, type: 'node' },
  { name: 'Stockholm', lat: 59.33, lon: 18.07, type: 'node' },
  // 北美
  { name: 'New York', lat: 40.71, lon: -74.01, type: 'hub' },
  { name: 'San Francisco', lat: 37.77, lon: -122.42, type: 'hub' },
  { name: 'Seattle', lat: 47.61, lon: -122.33, type: 'node' },
  { name: 'Toronto', lat: 43.65, lon: -79.38, type: 'node' },
  { name: 'Chicago', lat: 41.88, lon: -87.63, type: 'node' },
  { name: 'Mexico City', lat: 19.43, lon: -99.13, type: 'hot' },
  { name: 'Los Angeles', lat: 34.05, lon: -118.24, type: 'node' },
  // 南美
  { name: 'Sao Paulo', lat: -23.55, lon: -46.63, type: 'hot' },
  { name: 'Buenos Aires', lat: -34.6, lon: -58.38, type: 'node' },
  { name: 'Santiago', lat: -33.45, lon: -70.67, type: 'node' },
  { name: 'Bogota', lat: 4.71, lon: -74.07, type: 'node' },
  // 非洲 / 中东
  { name: 'Lagos', lat: 6.52, lon: 3.38, type: 'hot' },
  { name: 'Cairo', lat: 30.04, lon: 31.24, type: 'node' },
  { name: 'Johannesburg', lat: -26.2, lon: 28.05, type: 'node' },
  { name: 'Nairobi', lat: -1.29, lon: 36.82, type: 'node' },
  { name: 'Cape Town', lat: -33.92, lon: 18.42, type: 'node' },
];

/** 主要数据流弧线（按城市名索引） */
export const ARCS = [
  ['Shanghai', 'Tokyo'],
  ['Shanghai', 'Singapore'],
  ['Shanghai', 'London'],
  ['Shanghai', 'San Francisco'],
  ['Beijing', 'Moscow'],
  ['Beijing', 'Frankfurt'],
  ['Tokyo', 'Seoul'],
  ['Singapore', 'Sydney'],
  ['Singapore', 'Mumbai'],
  ['Mumbai', 'Dubai'],
  ['Dubai', 'London'],
  ['London', 'New York'],
  ['London', 'Lagos'],
  ['New York', 'San Francisco'],
  ['New York', 'Sao Paulo'],
  ['San Francisco', 'Sydney'],
  ['Frankfurt', 'Nairobi'],
  ['Tokyo', 'New York'],
];
