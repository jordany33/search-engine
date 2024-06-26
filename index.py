import re
import hashlib
#Only needed when downloading the punkt for the first time
#import nltk and nltk.download('punkt')
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, urldefrag
import zipfile
from nltk.stem import PorterStemmer
import json
import pickle
import sys
import io
import math

#Our index
index = {}
#Map of docid to URL
docMap = {}
#Alphanum constant
alphaNum = ["a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p","q","r","s","t","u","v","w","x","y","z","0","1","2","3","4","5","6","7","8","9"]
#How we track doc ID
curNum = 0

#Simhashing, seenURLs for dup URLs, and seenSimHash sets for near duplicate url and pages, then seen Hashes for exact duplicate content
seenURLs = set()
seenSimHash_values= set()
seenSimHashedUrls = set()
seenHashes = set()

#Get a 64 bit hash for the passed in list of tokens
def token_hash(tokens):
    hashedToks = []
    for token in tokens:
        hashVal = hashlib.md5(token.encode('utf-8')).digest()
        #Get only 64 bits of the hash as per prof reccomendation
        hashedToks.append(hashVal[:8])
    return hashedToks


#First generates hashes of tokens, then count the number of 1's and 0's in each column of each token hash, with 0's weighed -1, and 1's 1.
#Final count if positive makes the bit in the final hash at that position 1, else makes it 0
def makeSimhash(tokens):
    hashes = token_hash(tokens)
    finHash = 0
    #For each column, count zeroes and ones and use the sum value to decide on the corresponding bit for
    #hash of the page
    for x in range(0, 64):
        count = 0
        for hashVal in hashes:
            #Have to reverse the binary string we get here because we are reading it left to right
            #but trying to construct it right to left
            hashBin = bin(int.from_bytes(hashVal, 'little')).replace("0b","")
            hashBin = hashBin[::-1]
            #Ensure we have a digit at the place in the string if we are checking
            if x<len(hashBin) and hashBin[x] == '1':
                count = count + 1
            else:
                count = count - 1
        if count > 0:
            finHash = finHash + (1<<x)
    #Convert back to bytes since we seem to store hash as bytes by convention?
    return finHash.to_bytes(8, 'little')


#Returns the distance between hashes/number of bits where they are not the same
def distance(hash1, hash2):
    hash1 = int.from_bytes(hash1, 'little')
    hash2 = int.from_bytes(hash2, 'little')
    distance = bin(hash1 ^ hash2).count('1')
    return distance


#Compares URLs based on hash with previous urls, returning a bool determining if they are similar enough based on a threshold similarity value
def detectSimilarUrl(url) ->bool:
    global seenSimHashedUrls
    tokens = tokenize(url)
    simhash_url = makeSimhash(tokens)
    if any(distance(simhash_url, i) < 3 for i in seenSimHashedUrls):
        return True
    seenSimHashedUrls.add(simhash_url)
    return False

#Returns hash based on tokens, used to detect exact duplicates
def compute_hash(tokens):
    hash = hashlib.sha256()
    content = ' '.join(tokens)
    hash.update(content.encode('utf-8'))
    return hash.hexdigest()

#Return if list of tokens has been seen before
def exact_duplicate_detection(tokens):
    global seenHashes
    page_hash = compute_hash(tokens)
    if page_hash in seenHashes:
        return True
    seenHashes.add(page_hash)
    return False

#Compute simhash of our file using the passed in dictionary and returns a bool indicating if it was similar to previous ones or not
def simhashClose(tokens):
    global seenSimHash_values
    simhash_val = makeSimhash(tokens)
    if any(distance(simhash_val, i) < 5 for i in seenSimHash_values):
        return True
    seenSimHash_values.add(simhash_val)
    return False

#Posting class based on slides
class Posting:
    def __init__(self, docid, tfidf, fields, positions, count):
        self.docid = int(docid)
        self.tfidf = float(tfidf) # use freq counts for now
        self.positions = positions
        self.fields = fields
        if len(fields) == 0:
            fields["h1"] = 0
            fields["h2"] = 0
            fields["h3"] = 0
            fields["strong"] = 0
            fields["b"] = 0
            fields["title"] = 0
        else:
            for x in fields.keys():
                fields[x] = int(fields[x])
        self.count = int(count)
    #String print for our posting object
    def __str__(self):
        postStr = f':{self.docid}|{self.tfidf}|{self.count}|'
        for x in self.fields.values():
            postStr = postStr + ' ' +  str(x)
        postStr = postStr + '|'
        if self.positions == []:
            postStr = postStr + 'None'
        for x in self.positions:
            postStr = postStr + ' ' +  str(x)
        return postStr
    #String representation of posting object
    def __repr__(self):
        postStr = f':{self.docid}|{self.tfidf}|{self.count}|'
        for x in self.fields.values():
            postStr = postStr + ' ' +  str(x)
        postStr = postStr + '|'
        if self.positions == []:
            postStr = postStr + 'None'
        for x in self.positions:
            postStr = postStr + ' ' +  str(x)
        return postStr
    #Increment count and position list
    def addCount(self, pos):
        self.count += 1
        #Uncomment when doing positions
        #self.positions.append(pos)
    #Returns doc number of our post
    def getDoc(self):
        return self.docid
    #Returns tfidf of our post
    def getTfidf(self):
        return self.tfidf
    #Return total fields count for the term for this posting
    def getImpTxt(self):
        return sum(list(self.fields.values()))
    #Adds the val to fields for the posting object
    def addField(self, val):
        self.fields[val] += 1
        self.count += 1
    #Updates the tfidf value to be newVal
    def updateTfidf(self, newVal):
        self.tfidf = newVal
    #Returns tfidf of our post
    def getCount(self):
        return self.count

#Parses a line of input from the index and returns the corresponding term and list of postings that it parses and recreates
def parseStr(line):
    remadePosts = []
    #Splits it by delimiter to separate term and posts
    obj = line.split(':')
    #Gets term and slices it off so we have a list of just post strings
    term = obj[0]
    obj = obj[1:]
    #Recreates each post from each post str
    for post in obj:
        remadePosts.append(parsePost(post))
    #Returns term and post
    return term, remadePosts

#Parses a post str and turns it into a posting object which it returns
def parsePost(postStr):
    #Splits to get posting attributes
    attr = postStr.split('|')
    #Gets docid and tfidf by just getting the index because they're just an int
    docId = attr[0]
    tfidf = attr[1]
    count = attr[2]
    #Parses the list string to get the list values for fields and pos
    fields = parseDict(attr[3])
    pos = parseAttrList(attr[4])
    #Creates and returns posting object
    return (Posting(docId, tfidf, fields, pos, count))

#Parses a list string and returns a recreated list
def parseAttrList(listStr):
    #Represented empty lists as 'None' in our string representation of our posting, so if we see it return []
    if listStr == 'None':
        return []
    #Split the list str to get each element
    attrList = []
    elems = listStr.split()
    #Add each element to list we return, ensure no empty string is appended
    for x in elems:
        if x != '':
            attrList.append(x)
    #return the list
    return attrList

#Parses the given string to list by splitting it and assigning each split number to corresponding field
def parseDict(dicStr):
    counts = dicStr.split()
    fields = {}
    fields["h1"] = counts[0]
    fields["h2"] = counts[1]
    fields["h3"] = counts[2]
    fields["strong"] = counts[3]
    fields["b"] = counts[4]
    fields["title"] = counts[5]
    return fields

#Creates an index of indexes given the partial index name
def createIndexofIndexes(filename):
    #Initializes mapping and current position in file
    positions = {}
    current_position = 0

    #Opens file
    file = open(filename, 'r')
    while True:
        #While condition holds, go to the curPos value using seek and read the line
        file.seek(current_position)
        line = file.readline()

        #If no line, breaks
        if not line:
            break

        #Split by : and get the first element to get the word
        objs = line.split(':')
        word = objs[0]
        #Update mapping with word and its current position
        positions[word] = current_position

        #Move curPos pointer to the next line
        current_position += len(line)
    file.close()
    return positions

#Computes posting lists for the tokens provided for the given doc
def computeWordFrequencies(tokens) -> dict():
    global curNum
    #The mapped tokens to frequencies we return
    freq = dict()
    #Iterate through tokens, if not yet in dict, initialize the count to 1, otherwise increment the count by 1
    for t in range(len(tokens)):
        tok = tokens[t]
        if tok not in freq:
            #freq[tok] = Posting(curNum, 0, {}, [t], 1)
            freq[tok] = Posting(curNum, 0, {}, [], 1)
        else:
            freq[tok].addCount(t)
    return freq

#Reads the content and returns a list of the alphanumeric tokens within it
def tokenize(content: str) -> list['Tokens']:
    #Vars below are our current token we are building and the list of tokens respectively
    curTok = ''
    tokens = []
    file = None
    cur = 0
    #Going through the content string at a time
    while cur < len(content):
        #Read at most 5 chars
        c = content[cur]
        #converts character to lowercase if it is alpha, done since we don't care about capitalization, makes it easier to check given
        #we made our list's alpha characters only lowercase
        c = c.lower()
        #If c is alphanum, concatenate it to our current token, else add the current token to list if not empty string and start on a new token
        if c in alphaNum:
            curTok = curTok + c
        else:
            if curTok != '':
                tokens.append(curTok)
                curTok = ''
        cur = cur + 1
    #For when we reach the end of the content, check what our last token is
    #If our curTok isn't empty, add it to token list
    if curTok != '':
        tokens.append(curTok)
    return tokens

#Attempts to save our partial index using pickle
def pickleIndex() ->None:
    global index
    file = open("pickleIndex", "wb")
    pickle.dump(index, file)
    file.close()
    return

#Attempts to save our partial index
def partialIndex(partialNum) ->None:
    global index
    file = open(("partialIndex"+str(partialNum)), "w")
    #Prints out index entry to text file in the format term:post1:post2:...:postn
    for t,f in sorted(index.items(), key=(lambda x : (x[0])) ):
        print(t, end = '', file = file)
        f = sorted(f, key = (lambda p: p.getDoc()))
        for post in f:
            print(str(post), end = '', file = file)
        print(file=file)
    file.close()
    return

#Attempts to save seem our index using pickle
def pickleDocMap() ->None:
    global docMap
    file = open("pickleDocMap", "wb")
    pickle.dump(docMap, file)
    file.close()
    return

#Add fields to the posting objects given which fields to add
def addFields(postings, soup, field, stemmer):
    #Gets all tags and texts associated with the given tag
    texts = soup.find_all(field)
    #Extracts the text
    for text in texts:
        content = text.get_text()
        #tokenizes text
        tokens = [stemmer.stem(x) for x in tokenize(content)]
        #Updates the field list or creates new posting is term not yet seen
        #Can't really track positions of headers and bold reliably so we don't track positions for these tags, but
        #we still do for the regular tokens
        for tok in tokens:
            if tok in postings:
                postings[tok].addField(field)
            else:
                postings[tok] = Posting(curNum, 0, {}, [], 0)
                postings[tok].addField(field)

#Indexes anchor words
def indAnchor(postings, soup, stemmer):
    #Finds all anchor tags, then iterates through them
    texts = soup.find_all('a')
    for text in texts:
        #Gets the tokens, then updates/creates postings accordingly
        content = text.get_text()
        tokens = [stemmer.stem(x) for x in tokenize(content)]
        for t in range(len(tokens)):
            tok = tokens[t]
            if tok in postings:
                postings[tok].addCount(t)
            else:
                postings[tok] = Posting(curNum, 0, {}, [], 1)

#Generates our tfIdf score for the given list of documents for a term, ie we call this on each posting list for each term
def calcTFIDF(postings):
    global curNum
    tf_idfs = []
    total_contain_t = len(postings)

    for post in postings:
        post_freq = post.getCount()
        tfidf = (1 + math.log10(post_freq)) * (math.log10(curNum/total_contain_t))
        post.updateTfidf(tfidf)
    return

#Given the file names of the files that need to be merged, merges them into a partial index then returns the filename
#of the merged partials, creates the filename based on the tempIndexNum parameter that is passed in
def mergePartials(toMerge1, toMerge2, tempIndexNum) -> str:
    #Get index of indexes for each partial so it's easier to grab the item from the file
    indexOfIndex1 = [(x,y) for x,y in createIndexofIndexes(toMerge1).items()]
    indexOfIndex2 = [(x,y) for x,y in createIndexofIndexes(toMerge2).items()]

    #Open the partial index files
    file1 = open(toMerge1, 'r')
    file2 = open(toMerge2, 'r')

    #Make the string for the tempIndex and open it to start writing
    tempName = "tempIndex"+str(tempIndexNum)
    file3 = open(tempName, 'w')

    #Make variables for what line/term we're on and the total number of terms in each partial index
    ind1 = 0
    ind2 = 0
    len1 = len(indexOfIndex1)
    len2 = len(indexOfIndex2)

    #Iterate through until we reach the end of one file
    while ind1< len1 and ind2 < len2:
        #If alphanumerically word from index1< word from index 2, write it to file and increment wordnum/index1
        if indexOfIndex1[ind1][0] < indexOfIndex2[ind2][0]:
            file1.seek(indexOfIndex1[ind1][1])
            line = file1.readline().strip()
            print(line, file = file3)
            ind1 += 1
        #If alphanumerically word from index1> word from index 2, write the word from index2 to file and increment wordnum/index2
        elif indexOfIndex1[ind1][0] > indexOfIndex2[ind2][0]:
            file2.seek(indexOfIndex2[ind2][1])
            line = file2.readline().strip()
            print(line, file = file3)
            ind2 += 1
        #If words we're currently looking at for both partial indexes is equal, read the entire line for both
        #parse it, combine the posting objects and write it to file
        else:
            file1.seek(indexOfIndex1[ind1][1])
            line1 = file1.readline().strip()
            file2.seek(indexOfIndex2[ind2][1])
            line2 = file2.readline().strip()
            term, posts1 = parseStr(line1)
            term, posts2 = parseStr(line2)
            posts1.extend(posts2)
            posts1 = sorted(posts1, key = (lambda x: x.getDoc()))
            print(term, end = '', file = file3)
            for post in posts1:
                print(str(post), end = '', file = file3)
            print(file=file3)
            ind1 += 1
            ind2 += 1
    #Make sure if we didn't go through the entire file in the first while loop to print out all its line to new file here
    while ind1 < len1:
        file1.seek(indexOfIndex1[ind1][1])
        line = file1.readline().strip()
        print(line, file = file3)
        ind1 += 1
    while ind2 < len2:
        file1.seek(indexOfIndex2[ind2][1])
        line = file2.readline().strip()
        print(line, file = file3)
        ind2 += 1
    file1.close()
    file2.close()
    file3.close()
    return tempName

#Given the number of partial indexes, merges them together and updates the tfidf score from (frequency) to actual score
def mergeIndexes(partialNum) -> None:
    #Keeps track of our current temporary index filename
    curTemp = None
    partialIndString = 'partialIndex'
    for x in range(partialNum):
        if x == 0:
            curTemp = partialIndString + str(x)
        else:
            curTemp = mergePartials(curTemp, (partialIndString+str(x)), x)
    #Build final index and update tfidf scores
    indexOfIndex = createIndexofIndexes(curTemp)
    file1 = open(curTemp, 'r')
    file2 = open("FinalIndex", 'w')
    #Goes through index of indexes, gets line for each term, reads it, parases it, and updates the tfidf and prints updated line to new file
    for term, num in indexOfIndex.items():
        file1.seek(num)
        line = file1.readline().strip()
        term, posts = parseStr(line)
        calcTFIDF(posts)
        print(term, end = '', file = file2)
        for post in posts:
            print(str(post), end = '', file = file2)
        print(file=file2)
    file1.close()
    file2.close()

def build_index():
    global curNum
    global index
    partialInd = 0
    terms = set()
    #Opens zip file
    zip = zipfile.ZipFile("developer.zip", "r")
    #Iterates through all file in zip file
    for file in zip.infolist():
        #Checks its not a directory
        if not file.is_dir():
            #Opens json file and loads it
            doc = zip.open(file, 'r')
            file = json.load(doc)
            #Checks to see if it has a url field
            if file.get('url'):
                #Check for exact or near duplicate urls
                if (file.get('url') in seenURLs):
                    continue
                seenURLs.add(file.get('url'))
                #Checks if there is content
                if file.get('content'):
                    #Parses it
                    encode = 'utf8'
                    content = file.get('content')
                    if file.get('encoding'):
                        encode = file.get('encoding')
                        content.encode(encode)
                    parsed_text = BeautifulSoup(content, "html.parser", from_encoding = encode)
                    #Checks if parsed content is there
                    if parsed_text:
                        #Gets tokens then uses then for index, adding our cur doc to the index[token] for each token if not already there
                        ps = PorterStemmer()
                        text = parsed_text.get_text()
                        #Check for near or exact duplicate page content
                        simTokens = tokenize(text)
                        if simhashClose(simTokens) or exact_duplicate_detection(simTokens):
                            continue
                        tokens = [ps.stem(x) for x in tokenize(text)]
                        postings = computeWordFrequencies(tokens)
                        #Get the text with important fields and update them
                        indAnchor(postings, parsed_text, ps)
                        addFields(postings, parsed_text, 'b', ps)
                        addFields(postings, parsed_text, 'h1', ps)
                        addFields(postings, parsed_text, 'h2', ps)
                        addFields(postings, parsed_text, 'h3', ps)
                        addFields(postings, parsed_text, 'strong', ps)
                        addFields(postings, parsed_text, 'title', ps)
                        for term, post in postings.items():
                            #If not yet added but the term exist
                            if term in index:
                                index[term].append(post)
                            elif term not in index:
                                index[term] = [post]
                record = open("record.txt", "a")
                print(f"Current doc is {curNum}", file = record)
                print(f"Posting list for it is: {postings.keys()}", file = record)
                print(f"Index length is: {len(index)}", file = record)
                record.close()
                #Maps url to docid
                docMap[curNum] = (file.get('url'))
                curNum += 1
                if curNum % 10000 == 0 and curNum != 0:
                    partialIndex(partialInd)
                    partialInd += 1
                    index.clear()
    #pickleIndex()
    partialIndex(partialInd)
    partialInd += 1
    mergeIndexes(partialInd)
    pickleDocMap()
    stats = open("stats.txt", "w")
    print(f"Number of docs is: {curNum}", file = stats)
    print(f"Number of unique tokens/words is: {len(index)}", file = stats)
    stats.close()
if __name__ == "__main__":
    build_index()
    indOfInd = createIndexofIndexes("FinalIndex")
    file = open("indexOfIndexes", "wb")
    pickle.dump(indOfInd, file)
    file.close()
