[out:json][timeout:120];
(
  nwr["amenity"="parking"](35.40,139.50,35.82,139.95);
  nwr["highway"~"^(services|rest_area)$"](35.40,139.50,35.82,139.95);
  nwr["highway"="motorway_junction"](35.40,139.50,35.82,139.95);
  nwr["man_made"="tower"](35.40,139.50,35.82,139.95);
  nwr["name:en"~"^(Rainbow Bridge|Yokohama Bay Bridge|Tsurumi Tsubasa Bridge)$"](35.40,139.50,35.82,139.95);
);
out center tags;
