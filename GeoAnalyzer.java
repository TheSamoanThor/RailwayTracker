// GeoAnalyzer.java
import java.util.ArrayList;
import java.util.List;

public class GeoAnalyzer {

    /**
     * Результат фильтрации — возвращается в Python одним объектом,
     * чтобы не пересчитывать метрики в Python (иначе теряется весь
     * выигрыш производительности от Java).
     */
    public static class FilterResult {
        public final double centerLat;
        public final double centerLon;
        public final double avgDist;
        public final double threshold;
        public final int[] validIndices;

        public FilterResult(double centerLat, double centerLon,
                            double avgDist, double threshold,
                            int[] validIndices) {
            this.centerLat = centerLat;
            this.centerLon = centerLon;
            this.avgDist = avgDist;
            this.threshold = threshold;
            this.validIndices = validIndices;
        }
    }

    /**
     * Основной метод фильтрации выбросов.
     *
     * @param lats        массив широт
     * @param lons        массив долгот
     * @param multiplier  множитель порога
     * @return объект FilterResult со всеми метриками и индексами валидных точек
     */
    public static FilterResult filterOutliers(double[] lats, double[] lons,
                                              double multiplier) {
        int n = lats.length;
        if (n == 0) {
            return new FilterResult(0.0, 0.0, 0.0, 0.0, new int[0]);
        }

        // 1. Центр масс
        double sumLat = 0.0, sumLon = 0.0;
        for (int i = 0; i < n; i++) {
            sumLat += lats[i];
            sumLon += lons[i];
        }
        double centerLat = sumLat / n;
        double centerLon = sumLon / n;

        // 2. Среднее попарное расстояние (O(N^2))
        // Используем Math.sqrt(dx*dx + dy*dy) вместо Math.hypot —
        // быстрее и сопоставимо с math.sqrt в Python.
        double totalDist = 0.0;
        for (int i = 0; i < n; i++) {
            double latI = lats[i];
            double lonI = lons[i];
            for (int j = i + 1; j < n; j++) {
                double dLat = latI - lats[j];
                double dLon = lonI - lons[j];
                totalDist += Math.sqrt(dLat * dLat + dLon * dLon);
            }
        }
        double pairs = (double) n * (n - 1) / 2.0;
        double avgDist = pairs > 0 ? totalDist / pairs : 0.0;
        double threshold = multiplier * avgDist;

        // 3. Фильтрация по расстоянию до центра масс
        List<Integer> valid = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            double dLat = lats[i] - centerLat;
            double dLon = lons[i] - centerLon;
            double distToCenter = Math.sqrt(dLat * dLat + dLon * dLon);
            if (distToCenter <= threshold) {
                valid.add(i);
            }
        }

        int[] indices = new int[valid.size()];
        for (int i = 0; i < valid.size(); i++) {
            indices[i] = valid.get(i);
        }
        return new FilterResult(centerLat, centerLon, avgDist, threshold, indices);
    }
}
