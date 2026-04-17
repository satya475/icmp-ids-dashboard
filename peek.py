f = open('ids/data/KDDTrain+.txt', 'r')
for i, line in enumerate(f):
    print(line.strip())
    if i == 4:
        break
f.close()