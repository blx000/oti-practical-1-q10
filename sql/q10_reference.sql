-- Вариант 2. Детерминированная сортировка по custkey используется только при равной выручке.
SELECT c.custkey, c.name,
       sum(l.extendedprice * (1 - l.discount)) AS revenue,
       c.acctbal, n.name AS nation, c.address, c.phone, c.comment
FROM tpch.sf1.customer c
JOIN tpch.sf1.orders o ON c.custkey = o.custkey
JOIN tpch.sf1.lineitem l ON o.orderkey = l.orderkey
JOIN tpch.sf1.nation n ON c.nationkey = n.nationkey
WHERE o.orderdate >= DATE '1993-10-01'
  AND o.orderdate < DATE '1994-01-01'
  AND l.returnflag = 'R'
GROUP BY c.custkey, c.name, c.acctbal, n.name, c.address, c.phone, c.comment
ORDER BY revenue DESC, c.custkey
LIMIT 20;
