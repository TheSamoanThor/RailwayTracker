"""
Модуль маршрутизации по реальным ЖД путям (на основе локального GeoJSON).
Использует пространственный индекс для быстрого поиска.
"""
import json
import networkx as nx
from typing import List, Tuple, Optional
from simulation import haversine_km

class RailGraph:
    def __init__(self, geojson_path: str, grid_size: float = 0.2):
        self.G = nx.Graph()
        self.grid_size = grid_size
        self.spatial_grid = {}
        self._build_graph(geojson_path)

    def _get_grid_key(self, lat: float, lon: float) -> Tuple[int, int]:
        """Возвращает ключ ячейки сетки для координат."""
        return (int(lat / self.grid_size), int(lon / self.grid_size))

    def _build_graph(self, geojson_path: str):
        """Читает GeoJSON и строит граф с пространственным индексом."""
        try:
            with open(geojson_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        features = data.get("features", [])
        for feat in features:
            geom = feat.get("geometry") or {}
            if geom.get("type") != "LineString":
                continue
            coords = geom.get("coordinates", [])
            
            for i in range(len(coords) - 1):
                lon1, lat1 = coords[i][0], coords[i][1]
                lon2, lat2 = coords[i+1][0], coords[i+1][1]
                
                # Округляем для склейки линий
                n1 = (round(lat1, 4), round(lon1, 4))
                n2 = (round(lat2, 4), round(lon2, 4))
                
                if n1 == n2:
                    continue
                    
                dist = haversine_km(lat1, lon1, lat2, lon2)
                self.G.add_edge(n1, n2, weight=dist)

        # Строим пространственный индекс (сетку) для узлов
        for node in self.G.nodes:
            key = self._get_grid_key(node[0], node[1])
            if key not in self.spatial_grid:
                self.spatial_grid[key] = []
            self.spatial_grid[key].append(node)

    def find_nearest_node(self, lat: float, lon: float) -> Optional[Tuple[float, float]]:
        """Ищет ближайший узел, проверяя только соседние ячейки сетки."""
        if not self.G.nodes:
            return None
            
        cx, cy = self._get_grid_key(lat, lon)
        min_dist = float('inf')
        best_node = None
        
        # Проверяем 3x3 ячейки вокруг заданной точки
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                key = (cx + dx, cy + dy)
                for node in self.spatial_grid.get(key, []):
                    dist = haversine_km(lat, lon, node[0], node[1])
                    if dist < min_dist:
                        min_dist = dist
                        best_node = node
                        
        return best_node if min_dist < 50 else None

    def get_rail_route(self, from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> Optional[List[List[float]]]:
        """Ищет кратчайший путь по ЖД путям при помощи алгоритма Дейкстры."""
        if self.G.number_of_nodes() == 0:
            return None

        start_node = self.find_nearest_node(from_lat, from_lon)
        end_node = self.find_nearest_node(to_lat, to_lon)
        
        if not start_node or not end_node:
            return None

        try:
            path = nx.shortest_path(self.G, source=start_node, target=end_node, weight='weight')
            # Возвращаем в формате [[lat, lon], ...]
            return [[p[0], p[1]] for p in path]
        except nx.NetworkXNoPath:
            return None
